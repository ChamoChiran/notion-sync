import io
import json
import unittest
import urllib.error

from notion_sync.client import NotionClient
from notion_sync.config import Config
from notion_sync.errors import ConfigError, NotionApiError, PageRefError
from notion_sync.page_ref import PageRef
from notion_sync.parser import MarkdownParser
from notion_sync.renderer import MarkdownRenderer
from notion_sync.service import PageSyncService

PAGE_ID = "0123456789abcdef0123456789abcdef"


def text(content, **ann):
    item = {"type": "text", "plain_text": content, "text": {"content": content}}
    if ann:
        item["annotations"] = ann
    return item


def block(kind, content="", block_id="b", has_children=False, **extra):
    data = {"rich_text": [text(content)]} if content or kind == "paragraph" else {}
    data.update(extra)
    return {"id": block_id, "type": kind, kind: data, "has_children": has_children}


class PageRefTests(unittest.TestCase):
    def test_url_with_slug(self):
        ref = PageRef.parse(f"https://www.notion.so/My-Page-{PAGE_ID}")
        self.assertEqual(ref.id, PAGE_ID)

    def test_dashed_id(self):
        dashed = "01234567-89ab-cdef-0123-456789abcdef"
        self.assertEqual(PageRef.parse(dashed).id, PAGE_ID)

    def test_invalid(self):
        with self.assertRaises(PageRefError):
            PageRef.parse("not a page")


class ConfigTests(unittest.TestCase):
    def test_missing_token(self):
        with self.assertRaises(ConfigError):
            Config.from_env({})

    def test_token(self):
        self.assertEqual(Config.from_env({"NOTION_TOKEN": " abc "}).token, "abc")


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = MarkdownParser()

    def kinds(self, md):
        return [b["type"] for b in self.parser.parse(md)]

    def test_block_types(self):
        md = "# H\n\npara\n\n- a\n- [x] done\n1. one\n\n> q\n\n---\n\n```py\nprint(1)\n```\n"
        self.assertEqual(
            self.kinds(md),
            ["heading_1", "paragraph", "bulleted_list_item", "to_do",
             "numbered_list_item", "quote", "divider", "code"],
        )

    def test_nested_list(self):
        blocks = self.parser.parse("- a\n  - b\n    - c\n- d\n")
        self.assertEqual(len(blocks), 2)
        child = blocks[0]["bulleted_list_item"]["children"][0]
        self.assertIn("children", child["bulleted_list_item"])

    def test_todo_checked(self):
        blocks = self.parser.parse("- [x] a\n- [ ] b\n")
        self.assertEqual([b["to_do"]["checked"] for b in blocks], [True, False])

    def test_inline_formatting(self):
        rich = self.parser.parse("a **b** `c` [d](https://x.io)")[0]["paragraph"]["rich_text"]
        self.assertTrue(rich[1]["annotations"]["bold"])
        self.assertTrue(rich[3]["annotations"]["code"])
        self.assertEqual(rich[5]["text"]["link"]["url"], "https://x.io")

    def test_long_text_is_chunked(self):
        rich = self.parser.parse("x" * 4500)[0]["paragraph"]["rich_text"]
        self.assertEqual([len(r["text"]["content"]) for r in rich], [2000, 2000, 500])

    def test_placeholder_comments_skipped(self):
        self.assertEqual(self.kinds("<!-- unsupported block: table -->\n"), [])


class RendererTests(unittest.TestCase):
    def render(self, blocks, children=None):
        children = children or {}
        return MarkdownRenderer(lambda bid: children[bid]).render(blocks)

    def test_basic(self):
        out = self.render([
            block("heading_2", "Title"),
            block("paragraph", "hello"),
            block("bulleted_list_item", "a"),
            block("bulleted_list_item", "b"),
        ])
        self.assertEqual(out, "## Title\n\nhello\n\n- a\n- b\n")

    def test_numbering_and_nesting(self):
        out = self.render(
            [block("numbered_list_item", "one", "p", has_children=True),
             block("numbered_list_item", "two")],
            {"p": [block("bulleted_list_item", "kid")]},
        )
        self.assertEqual(out, "1. one\n    - kid\n2. two\n")

    def test_annotations(self):
        b = {"id": "x", "type": "paragraph", "has_children": False,
             "paragraph": {"rich_text": [text("hi", bold=True)]}}
        self.assertEqual(self.render([b]), "**hi**\n")

    def test_unsupported(self):
        out = self.render([{"id": "x", "type": "table", "table": {}, "has_children": False}])
        self.assertEqual(out, "<!-- unsupported block: table -->\n")

    def test_roundtrip_simple(self):
        md = "# T\n\nhello world\n\n- a\n- b\n"
        blocks = MarkdownParser().parse(md)
        for b in blocks:  # parser output lacks plain_text; fill it as Notion would
            for r in b[b["type"]].get("rich_text", []):
                r["plain_text"] = r["text"]["content"]
            b["has_children"] = False
        self.assertEqual(self.render(blocks), md)


class FakeClient:
    def __init__(self, existing):
        self.existing = existing
        self.deleted = []
        self.appended = None

    def list_children(self, block_id):
        return self.existing

    def delete_block(self, block_id):
        self.deleted.append(block_id)

    def append_children(self, block_id, blocks):
        self.appended = (block_id, blocks)

    def search_pages(self, query):
        return [{"id": "1", "url": "u", "properties": {
            "Name": {"type": "title", "title": [{"plain_text": "Doc"}]}}}]


class ServiceTests(unittest.TestCase):
    def test_push_replaces_content(self):
        client = FakeClient([block("paragraph", "old", "o1"), block("paragraph", "old", "o2")])
        result = PageSyncService(client).push(PageRef(PAGE_ID), "# New\n\ntext\n")
        self.assertEqual(client.deleted, ["o1", "o2"])
        self.assertEqual(client.appended[0], PAGE_ID)
        self.assertEqual((result.blocks_written, result.blocks_removed), (2, 2))

    def test_search(self):
        hit = PageSyncService(FakeClient([])).search("doc")[0]
        self.assertEqual((hit.page_id, hit.title), ("1", "Doc"))


class ClientTests(unittest.TestCase):
    def http_error(self, code, retry_after=None):
        headers = {"Retry-After": retry_after} if retry_after else {}
        return urllib.error.HTTPError("u", code, "err", headers, io.BytesIO(b"boom"))

    def make(self, responses):
        calls = []
        sleeps = []

        def opener(req):
            calls.append(req)
            r = responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return io.BytesIO(json.dumps(r).encode())

        return NotionClient(Config("t"), opener=opener, sleep=sleeps.append), calls, sleeps

    def test_retries_on_429(self):
        client, calls, sleeps = self.make([self.http_error(429, "3"), {"results": [], "has_more": False}])
        self.assertEqual(client.list_children("b"), [])
        self.assertEqual((len(calls), sleeps), (2, [3.0]))

    def test_error_raises(self):
        client, _, _ = self.make([self.http_error(404)])
        with self.assertRaises(NotionApiError) as ctx:
            client.list_children("b")
        self.assertEqual(ctx.exception.status, 404)

    def test_pagination(self):
        client, calls, _ = self.make([
            {"results": [1], "has_more": True, "next_cursor": "c"},
            {"results": [2], "has_more": False},
        ])
        self.assertEqual(client.list_children("b"), [1, 2])
        self.assertIn("start_cursor=c", calls[1].full_url)

    def test_append_batches(self):
        client, calls, _ = self.make([{}, {}, {}])
        client.append_children("b", [{}] * 250)
        self.assertEqual(len(calls), 3)


if __name__ == "__main__":
    unittest.main()
