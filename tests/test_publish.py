import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from notion_sync.cli import Cli
from notion_sync.documents import DocumentLoader, FrontMatterParser
from notion_sync.errors import ConfigError, NotionApiError
from notion_sync.links import LinkRewriter
from notion_sync.properties import PagePropertyBuilder
from notion_sync.publisher import DocsPublisher
from notion_sync.state import PublishState

PARENT = "0123456789abcdef0123456789abcdef"


class FrontMatterTests(unittest.TestCase):
    def test_parses_and_strips(self):
        meta, body = FrontMatterParser().parse(
            "---\ntype: Policy\nLast reviewed: 2026-10-15\nowner: \"A B\"\n---\n\n# Hi\n")
        self.assertEqual(meta, {"type": "Policy", "last_reviewed": "2026-10-15", "owner": "A B"})
        self.assertEqual(body, "# Hi\n")

    def test_no_front_matter(self):
        self.assertEqual(FrontMatterParser().parse("# Hi\n"), ({}, "# Hi\n"))

    def test_unterminated_is_ignored(self):
        text = "---\nkey: v\n# no end\n"
        self.assertEqual(FrontMatterParser().parse(text), ({}, text))


class LoaderTests(unittest.TestCase):
    def test_load(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "architecture").mkdir()
            (root / "architecture" / "a.md").write_text("# Title A\n\nbody\n", encoding="utf-8")
            (root / ".hidden").mkdir()
            (root / ".hidden" / "x.md").write_text("# no", encoding="utf-8")
            (root / "untitled-doc.md").write_text("text only\n", encoding="utf-8")
            docs = DocumentLoader().load(root)
        self.assertEqual([x.path for x in docs], ["architecture/a.md", "untitled-doc.md"])
        self.assertEqual(docs[0].title, "Title A")
        self.assertEqual(docs[0].body, "body\n")  # H1 moved into the title
        self.assertEqual(docs[1].title, "untitled doc")


class LinkTests(unittest.TestCase):
    def setUp(self):
        self.rw = LinkRewriter({"architecture/a.md": "11111111-1111-1111-1111-111111111111",
                                "b.md": "22222222-2222-2222-2222-222222222222"})

    def test_relative_links_rewritten(self):
        out = self.rw.rewrite("see [a](a.md#x) and [b](../b.md)", "architecture/c.md")
        self.assertIn("(https://www.notion.so/11111111111111111111111111111111)", out)
        self.assertIn("(https://www.notion.so/22222222222222222222222222222222)", out)

    def test_unknown_and_absolute_left_alone(self):
        text = "[x](missing.md) [y](https://e.com/a.md) [z](folder/)"
        self.assertEqual(self.rw.rewrite(text, "architecture/c.md"), text)


class PropertyTests(unittest.TestCase):
    def doc(self, path, **meta):
        from notion_sync.documents import Document
        return Document(path=path, title="T", body="b\n", meta=meta)

    def test_type_from_path_and_front_matter(self):
        b = PagePropertyBuilder("https://git/x/blob/main/")
        p = b.build(self.doc("architecture/decisions/0001.md", status="Approved",
                             owner="Me", last_reviewed="2026-10-15", component="Backend API"))
        self.assertEqual(p["Type"], {"select": {"name": "ADR"}})
        self.assertEqual(p["Status"]["select"]["name"], "Approved")
        self.assertEqual(p["Last reviewed"], {"date": {"start": "2026-10-15"}})
        self.assertEqual(p["Source"], {"url": "https://git/x/blob/main/architecture/decisions/0001.md"})
        self.assertEqual(b.build(self.doc("README.md"))["Type"]["select"]["name"], "Guide")
        self.assertEqual(b.build(self.doc("x.md", type="Policy"))["Type"]["select"]["name"], "Policy")

    def test_bad_date_omitted(self):
        p = PagePropertyBuilder().build(self.doc("x.md", last_reviewed="soon"))
        self.assertNotIn("Last reviewed", p)
        self.assertNotIn("Source", p)


class FakeClient:
    def __init__(self):
        self.calls = []
        self.n = 0
        self.fail_404_for = set()

    def _id(self):
        self.n += 1
        return f"00000000-0000-0000-0000-{self.n:012d}"

    def create_database(self, parent, title, props):
        self.calls.append(("create_database", parent, title))
        return {"id": "db-1", "data_sources": [{"id": "ds-1"}]}

    def create_page(self, ds, props):
        pid = self._id()
        self.calls.append(("create_page", ds, props["Name"]["title"][0]["text"]["content"], pid))
        return {"id": pid}

    def update_page(self, pid, properties=None, in_trash=None):
        if pid in self.fail_404_for:
            raise NotionApiError(404, "PATCH", "/x", "{}")
        self.calls.append(("update_page", pid, in_trash))

    def replace_markdown(self, pid, body, allow_deleting_content=False):
        self.calls.append(("replace", pid, body))


class PublisherTests(unittest.TestCase):
    def make_root(self, d):
        root = Path(d) / "docs"
        (root / "architecture").mkdir(parents=True)
        (root / "architecture" / "a.md").write_text("# A\n\nsee [b](b.md)\n", encoding="utf-8")
        (root / "architecture" / "b.md").write_text("# B\n\ntext\n", encoding="utf-8")
        return root

    def names(self, client, kind):
        return [c for c in client.calls if c[0] == kind]

    def test_first_run_creates_database_pages_and_rewrites_links(self):
        with tempfile.TemporaryDirectory() as d:
            root, state = self.make_root(d), Path(d) / "map.json"
            client = FakeClient()
            report = DocsPublisher(client).publish(root, state, parent=PARENT, title="Docs")
            saved = json.loads(state.read_text(encoding="utf-8"))
        self.assertEqual((report.created, report.updated, report.unchanged), (2, 2, 0))
        self.assertEqual(self.names(client, "create_database")[0][1],
                         {"type": "page_id", "page_id": PARENT})
        self.assertEqual(saved["data_source_id"], "ds-1")
        self.assertEqual(set(saved["pages"]), {"architecture/a.md", "architecture/b.md"})
        a_body = next(c[2] for c in self.names(client, "replace")
                      if "see" in c[2])
        b_id = saved["pages"]["architecture/b.md"]["id"].replace("-", "")
        self.assertIn(f"https://www.notion.so/{b_id}", a_body)

    def test_second_run_skips_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            root, state = self.make_root(d), Path(d) / "map.json"
            DocsPublisher(FakeClient()).publish(root, state, parent=PARENT)
            client = FakeClient()
            report = DocsPublisher(client).publish(root, state)
            self.assertEqual((report.created, report.updated, report.unchanged), (0, 0, 2))
            self.assertEqual(client.calls, [])
            (root / "architecture" / "b.md").write_text("# B\n\nchanged\n", encoding="utf-8")
            report = DocsPublisher(client).publish(root, state)
        self.assertEqual((report.updated, report.unchanged), (1, 1))

    def test_workspace_parent(self):
        with tempfile.TemporaryDirectory() as d:
            client = FakeClient()
            DocsPublisher(client).publish(self.make_root(d), Path(d) / "m.json", parent="Workspace")
        self.assertEqual(self.names(client, "create_database")[0][1],
                         {"type": "workspace", "workspace": True})

    def test_requires_parent_on_first_run(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ConfigError):
                DocsPublisher(FakeClient()).publish(self.make_root(d), Path(d) / "m.json")

    def test_prune_trashes_removed_files(self):
        with tempfile.TemporaryDirectory() as d:
            root, state = self.make_root(d), Path(d) / "map.json"
            DocsPublisher(FakeClient()).publish(root, state, parent=PARENT)
            (root / "architecture" / "b.md").unlink()
            client = FakeClient()
            report = DocsPublisher(client).publish(root, state, prune=True)
            saved = json.loads(state.read_text(encoding="utf-8"))
        self.assertEqual(report.trashed, 1)
        self.assertEqual(list(saved["pages"]), ["architecture/a.md"])
        self.assertTrue(any(c[0] == "update_page" and c[2] is True for c in client.calls))

    def test_page_deleted_in_notion_is_recreated(self):
        with tempfile.TemporaryDirectory() as d:
            root, state = self.make_root(d), Path(d) / "map.json"
            DocsPublisher(FakeClient()).publish(root, state, parent=PARENT)
            old = PublishState(state).pages["architecture/b.md"]["id"]
            (root / "architecture" / "b.md").write_text("# B\n\nedit\n", encoding="utf-8")
            client = FakeClient()
            client.fail_404_for = {old}
            report = DocsPublisher(client).publish(root, state)
            new = PublishState(state).pages["architecture/b.md"]["id"]
        self.assertNotEqual(old, new)
        self.assertEqual(report.updated, 1)

    def test_cli_publish(self):
        class FakePublisher:
            def publish(self, folder, state, **kw):
                self.args = (folder, state, kw)
                from notion_sync.publisher import PublishReport
                return PublishReport(created=2, updated=1, unchanged=3, trashed=0)

        pub = FakePublisher()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = Cli(publisher_factory=lambda: pub).run(
                ["publish", "docs", "--parent", PARENT, "--prune", "--source-url", "https://g/"])
        self.assertEqual(code, 0)
        self.assertIn("2 created, 1 updated, 3 unchanged, 0 trashed", out.getvalue())
        self.assertEqual(pub.args[0:2], ("docs", "notion-map.json"))
        self.assertTrue(pub.args[2]["prune"])
        self.assertEqual(pub.args[2]["source_base_url"], "https://g/")


if __name__ == "__main__":
    unittest.main()
