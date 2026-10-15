import contextlib
import io
import json
import os
import tempfile
import unittest
import urllib.error

from notion_sync.cli import Cli
from notion_sync.client import NotionClient
from notion_sync.config import Config
from notion_sync.errors import ConfigError, NotionApiError, NotionSyncError, PageRefError
from notion_sync.page_ref import PageRef
from notion_sync.service import PageSyncService

PAGE_ID = "0123456789abcdef0123456789abcdef"


class PageRefTests(unittest.TestCase):
    def test_url_with_slug_ending_in_hex_char(self):
        self.assertEqual(PageRef.parse(f"https://www.notion.so/My-Page-{PAGE_ID}").id, PAGE_ID)

    def test_url_with_query(self):
        self.assertEqual(PageRef.parse(f"https://notion.so/{PAGE_ID}?v=1").id, PAGE_ID)

    def test_dashed_id(self):
        self.assertEqual(PageRef.parse("01234567-89ab-cdef-0123-456789abcdef").id, PAGE_ID)

    def test_invalid(self):
        with self.assertRaises(PageRefError):
            PageRef.parse("not a page")


class ConfigTests(unittest.TestCase):
    def test_missing_token(self):
        with self.assertRaises(ConfigError):
            Config.from_env({})

    def test_token_and_default_version(self):
        cfg = Config.from_env({"NOTION_TOKEN": " abc "})
        self.assertEqual((cfg.token, cfg.notion_version), ("abc", "2026-03-11"))


class ClientTests(unittest.TestCase):
    def http_error(self, code, body=b"boom", retry_after=None):
        headers = {"Retry-After": retry_after} if retry_after else {}
        return urllib.error.HTTPError("u", code, "err", headers, io.BytesIO(body))

    def make(self, responses):
        calls, sleeps = [], []

        def opener(req):
            calls.append(req)
            r = responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return io.BytesIO(json.dumps(r).encode())

        return NotionClient(Config("tok"), opener=opener, sleep=sleeps.append), calls, sleeps

    def test_get_markdown_request(self):
        client, calls, _ = self.make([{"markdown": "# hi"}])
        self.assertEqual(client.get_markdown("p1")["markdown"], "# hi")
        req = calls[0]
        self.assertEqual((req.get_method(), req.full_url),
                         ("GET", "https://api.notion.com/v1/pages/p1/markdown"))
        self.assertEqual(req.get_header("Authorization"), "Bearer tok")
        self.assertEqual(req.get_header("Notion-version"), "2026-03-11")

    def test_replace_markdown_body(self):
        client, calls, _ = self.make([{}, {}])
        client.replace_markdown("p1", "# new")
        client.replace_markdown("p1", "# new", allow_deleting_content=True)
        plain, allowed = (json.loads(c.data) for c in calls)
        self.assertEqual(plain, {"type": "replace_content",
                                 "replace_content": {"new_str": "# new"}})
        self.assertTrue(allowed["replace_content"]["allow_deleting_content"])
        self.assertEqual(calls[0].get_method(), "PATCH")

    def test_update_markdown_body(self):
        client, calls, _ = self.make([{}])
        client.update_markdown("p1", [("a", "b"), ("c", "d")], replace_all_matches=True)
        body = json.loads(calls[0].data)
        self.assertEqual(body["type"], "update_content")
        self.assertEqual(body["update_content"]["content_updates"], [
            {"old_str": "a", "new_str": "b", "replace_all_matches": True},
            {"old_str": "c", "new_str": "d", "replace_all_matches": True},
        ])

    def test_retries_on_429_honoring_retry_after(self):
        client, calls, sleeps = self.make([self.http_error(429, retry_after="3"), {"ok": 1}])
        self.assertEqual(client.get_markdown("p1"), {"ok": 1})
        self.assertEqual((len(calls), sleeps), (2, [3.0]))

    def test_gives_up_after_max_attempts(self):
        client, calls, _ = self.make([self.http_error(503) for _ in range(6)])
        with self.assertRaises(NotionApiError):
            client.get_markdown("p1")
        self.assertEqual(len(calls), 6)

    def test_error_message_parsed(self):
        body = json.dumps({"code": "object_not_found", "message": "no page"}).encode()
        client, _, _ = self.make([self.http_error(404, body)])
        with self.assertRaises(NotionApiError) as ctx:
            client.get_markdown("p1")
        self.assertEqual((ctx.exception.status, ctx.exception.code), (404, "object_not_found"))
        self.assertIn("no page", str(ctx.exception))

    def test_non_retryable_error_not_retried(self):
        client, calls, _ = self.make([self.http_error(400)])
        with self.assertRaises(NotionApiError):
            client.get_markdown("p1")
        self.assertEqual(len(calls), 1)

    def test_search_filters_to_pages(self):
        client, _, _ = self.make([{"results": [{"object": "page", "id": "1"},
                                               {"object": "database", "id": "2"}]}])
        self.assertEqual([p["id"] for p in client.search_pages("x")], ["1"])


class FakeClient:
    def __init__(self, markdown_response=None):
        self.markdown_response = markdown_response or {"markdown": "# hi"}
        self.calls = []

    def get_markdown(self, page_id):
        self.calls.append(("get", page_id))
        return self.markdown_response

    def replace_markdown(self, page_id, markdown, allow_deleting_content=False):
        self.calls.append(("replace", page_id, markdown, allow_deleting_content))

    def update_markdown(self, page_id, replacements, replace_all_matches=False):
        self.calls.append(("update", page_id, replacements, replace_all_matches))

    def search_pages(self, query):
        return [{"id": "1", "url": "u", "properties": {
            "Name": {"type": "title", "title": [{"plain_text": "Doc"}]}}}]


class ServiceTests(unittest.TestCase):
    def test_pull(self):
        pulled = PageSyncService(FakeClient()).pull(PageRef(PAGE_ID))
        self.assertEqual((pulled.markdown, pulled.truncated), ("# hi", False))

    def test_pull_truncated(self):
        client = FakeClient({"markdown": "x", "truncated": True, "unknown_block_ids": ["a"]})
        pulled = PageSyncService(client).pull(PageRef(PAGE_ID))
        self.assertEqual((pulled.truncated, pulled.unknown_block_ids), (True, ["a"]))

    def test_push_and_edit_delegate(self):
        client = FakeClient()
        service = PageSyncService(client)
        service.push(PageRef(PAGE_ID), "# new", allow_deleting_content=True)
        service.edit(PageRef(PAGE_ID), [("a", "b")], replace_all=True)
        self.assertEqual(client.calls, [
            ("replace", PAGE_ID, "# new", True),
            ("update", PAGE_ID, [("a", "b")], True),
        ])

    def test_search(self):
        hit = PageSyncService(FakeClient()).search("doc")[0]
        self.assertEqual((hit.page_id, hit.title), ("1", "Doc"))


class CliTests(unittest.TestCase):
    def run_cli(self, argv, client=None):
        client = client or FakeClient()
        cli = Cli(service_factory=lambda: PageSyncService(client))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.run(argv)
        return code, out.getvalue(), err.getvalue(), client

    def test_pull_to_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "doc.md")
            code, out, _, _ = self.run_cli(["pull", PAGE_ID, "-o", path])
            self.assertEqual(code, 0)
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "# hi")

    def test_push_reads_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "doc.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write("# from file")
            code, _, _, client = self.run_cli(["push", path, PAGE_ID, "--allow-deleting-content"])
        self.assertEqual(code, 0)
        self.assertEqual(client.calls, [("replace", PAGE_ID, "# from file", True)])

    def test_edit_repeatable_replace(self):
        code, _, _, client = self.run_cli(
            ["edit", PAGE_ID, "-r", "a", "b", "-r", "c", "d", "--all"])
        self.assertEqual(code, 0)
        self.assertEqual(client.calls, [("update", PAGE_ID, [("a", "b"), ("c", "d")], True)])

    def test_search_output(self):
        code, out, _, _ = self.run_cli(["search", "doc"])
        self.assertEqual((code, out), (0, "1  Doc  u\n"))

    def test_error_returns_nonzero(self):
        class Boom(FakeClient):
            def get_markdown(self, page_id):
                raise NotionSyncError("boom")

        code, _, err, _ = self.run_cli(["pull", PAGE_ID], Boom())
        self.assertEqual(code, 1)
        self.assertIn("error: boom", err)

    def test_bad_page_ref_is_user_error(self):
        code, _, err, _ = self.run_cli(["pull", "nope"])
        self.assertEqual(code, 1)
        self.assertIn("cannot find a page ID", err)


if __name__ == "__main__":
    unittest.main()
