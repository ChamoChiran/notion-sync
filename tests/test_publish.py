import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from notion_sync.cli import Cli
from notion_sync.documents import Document, DocumentLoader, FrontMatterParser
from notion_sync.errors import ConfigError, NotionApiError
from notion_sync.links import LinkRewriter
from notion_sync.publisher import DocsPublisher
from notion_sync.service import PageSyncService
from notion_sync.state import PublishState
from notion_sync.page_ref import PageRef

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
        # top-level files first, then folders
        self.assertEqual([x.path for x in docs], ["untitled-doc.md", "architecture/a.md"])
        self.assertEqual(docs[1].title, "Title A")
        self.assertEqual(docs[1].body, "body\n")  # H1 moved into the title
        self.assertEqual(docs[0].title, "untitled doc")


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


class FakeClient:
    """Records calls; page ids are sequential so parents can be checked."""

    def __init__(self):
        self.calls = []
        self.n = 0
        self.fail_404_for = set()
        self.titles = {}

    def create_page(self, parent, title):
        self.n += 1
        pid = f"00000000-0000-0000-0000-{self.n:012d}"
        self.titles[pid] = title
        self.calls.append(("create_page", parent, title, pid))
        return {"id": pid}

    def set_title(self, pid, title):
        if pid in self.fail_404_for:
            raise NotionApiError(404, "PATCH", "/x", "{}")
        self.titles[pid] = title
        self.calls.append(("set_title", pid, title))

    def replace_markdown(self, pid, body, allow_deleting_content=False):
        if pid in self.fail_404_for:
            raise NotionApiError(404, "PATCH", "/x", "{}")
        self.calls.append(("replace", pid, body))

    def trash_page(self, pid):
        self.calls.append(("trash_page", pid))

    def trash_database(self, did):
        self.calls.append(("trash_database", did))


class PublisherTests(unittest.TestCase):
    def make_root(self, d):
        root = Path(d) / "docs"
        (root / "architecture" / "components").mkdir(parents=True)
        (root / "README.md").write_text("# Guide\n\nsee [a](architecture/a.md)\n", encoding="utf-8")
        (root / "architecture" / "a.md").write_text(
            "---\nstatus: Draft\nowner: Me\n---\n\n# A\n\ntext\n", encoding="utf-8")
        (root / "architecture" / "components" / "c.md").write_text("# C\n\ntext\n", encoding="utf-8")
        return root

    def pages(self, client):
        return [c for c in client.calls if c[0] == "create_page"]

    def test_first_run_builds_tree(self):
        with tempfile.TemporaryDirectory() as d:
            root, state = self.make_root(d), Path(d) / "map.json"
            client = FakeClient()
            report = DocsPublisher(client).publish(root, state, parent=PARENT, title="Centric Docs")
            saved = json.loads(state.read_text(encoding="utf-8"))

        # root + 'architecture' + 'architecture/components' + 3 docs
        self.assertEqual((report.created, report.updated, report.unchanged), (5, 3, 0))
        titles = [client.titles[c[3]] for c in self.pages(client)]
        self.assertEqual(titles, ["Centric Docs", "Guide", "Architecture", "A", "Components", "C"])
        by_title = {client.titles[c[3]]: c for c in self.pages(client)}
        root_id = saved["root_id"]
        self.assertEqual(by_title["Centric Docs"][1], {"type": "page_id", "page_id": PARENT})
        self.assertEqual(by_title["Guide"][1]["page_id"], root_id)
        self.assertEqual(by_title["Architecture"][1]["page_id"], root_id)
        self.assertEqual(by_title["A"][1]["page_id"], saved["folders"]["architecture"])
        self.assertEqual(by_title["Components"][1]["page_id"], saved["folders"]["architecture"])
        self.assertEqual(by_title["C"][1]["page_id"], saved["folders"]["architecture/components"])
        self.assertEqual(saved["version"], 3)

    def test_content_has_header_and_rewritten_links(self):
        with tempfile.TemporaryDirectory() as d:
            root, state = self.make_root(d), Path(d) / "map.json"
            client = FakeClient()
            DocsPublisher(client).publish(root, state, parent=PARENT)
            saved = json.loads(state.read_text(encoding="utf-8"))
        bodies = {c[1]: c[2] for c in client.calls if c[0] == "replace"}
        a_id = saved["pages"]["architecture/a.md"]["id"]
        self.assertTrue(bodies[a_id].startswith("> **Status:** Draft · **Owner:** Me\n\ntext"))
        guide = bodies[saved["pages"]["README.md"]["id"]]
        self.assertIn("https://www.notion.so/" + a_id.replace("-", ""), guide)

    def test_workspace_parent(self):
        with tempfile.TemporaryDirectory() as d:
            client = FakeClient()
            DocsPublisher(client).publish(self.make_root(d), Path(d) / "m.json", parent="Workspace")
        self.assertEqual(self.pages(client)[0][1], {"type": "workspace", "workspace": True})

    def test_second_run_skips_unchanged_then_updates_changed(self):
        with tempfile.TemporaryDirectory() as d:
            root, state = self.make_root(d), Path(d) / "map.json"
            DocsPublisher(FakeClient()).publish(root, state, parent=PARENT)
            client = FakeClient()
            report = DocsPublisher(client).publish(root, state)
            self.assertEqual((report.created, report.updated, report.unchanged), (0, 0, 3))
            self.assertEqual(client.calls, [])
            (root / "architecture" / "components" / "c.md").write_text("# C\n\nchanged\n", encoding="utf-8")
            report = DocsPublisher(client).publish(root, state)
        self.assertEqual((report.updated, report.unchanged), (1, 2))

    def test_requires_parent_on_first_run(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ConfigError):
                DocsPublisher(FakeClient()).publish(self.make_root(d), Path(d) / "m.json")

    def test_old_database_state_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "map.json"
            state.write_text(json.dumps({"database_id": "x", "pages": {"README.md": {"id": "old", "hash": "h"}}}),
                             encoding="utf-8")
            self.assertEqual(PublishState(state).pages, {})

    def test_prune_trashes_removed_files_and_empty_folders(self):
        with tempfile.TemporaryDirectory() as d:
            root, state = self.make_root(d), Path(d) / "map.json"
            DocsPublisher(FakeClient()).publish(root, state, parent=PARENT)
            before = json.loads(state.read_text(encoding="utf-8"))
            (root / "architecture" / "components" / "c.md").unlink()
            client = FakeClient()
            report = DocsPublisher(client).publish(root, state, prune=True)
            after = json.loads(state.read_text(encoding="utf-8"))
        self.assertEqual(report.trashed, 2)  # the doc and the now-empty 'components' folder
        self.assertEqual(set(after["pages"]), {"README.md", "architecture/a.md"})
        self.assertEqual(set(after["folders"]), {"architecture"})
        trashed = [c[1] for c in client.calls if c[0] == "trash_page"]
        self.assertEqual(set(trashed), {before["pages"]["architecture/components/c.md"]["id"],
                                        before["folders"]["architecture/components"]})

    def test_page_deleted_in_notion_is_recreated_under_same_parent(self):
        with tempfile.TemporaryDirectory() as d:
            root, state = self.make_root(d), Path(d) / "map.json"
            DocsPublisher(FakeClient()).publish(root, state, parent=PARENT)
            before = PublishState(state)
            old = before.pages["architecture/a.md"]["id"]
            (root / "architecture" / "a.md").write_text("# A\n\nedited\n", encoding="utf-8")
            client = FakeClient()
            client.fail_404_for = {old}
            report = DocsPublisher(client).publish(root, state)
            after = PublishState(state)
        self.assertNotEqual(old, after.pages["architecture/a.md"]["id"])
        self.assertEqual(self.pages(client)[0][1]["page_id"], before.folders["architecture"])
        self.assertEqual(report.updated, 1)

    def test_every_page_gets_a_title(self):
        """Regression: pages created without an explicit title show as 'Untitled' in Notion."""
        with tempfile.TemporaryDirectory() as d:
            client = FakeClient()
            DocsPublisher(client).publish(self.make_root(d), Path(d) / "m.json", parent=PARENT,
                                          title="Centric Docs")
        created = [c[3] for c in self.pages(client)]
        self.assertEqual(len(created), 6)
        self.assertTrue(all(client.titles[pid].strip() for pid in created))
        self.assertEqual(client.titles[created[0]], "Centric Docs")
        self.assertIn("Architecture", client.titles.values())

    def test_renamed_title_updates_the_page(self):
        with tempfile.TemporaryDirectory() as d:
            root, state = self.make_root(d), Path(d) / "map.json"
            DocsPublisher(FakeClient()).publish(root, state, parent=PARENT)
            (root / "architecture" / "a.md").write_text(
                "---\nstatus: Draft\nowner: Me\n---\n\n# A Renamed\n\ntext\n", encoding="utf-8")
            client = FakeClient()
            report = DocsPublisher(client).publish(root, state)
        self.assertEqual((report.updated, report.unchanged), (1, 2))
        self.assertEqual([c[2] for c in client.calls if c[0] == "set_title"], ["A Renamed"])

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
                ["publish", "docs", "--parent", "workspace", "--prune"])
        self.assertEqual(code, 0)
        self.assertIn("2 created, 1 updated, 3 unchanged, 0 trashed", out.getvalue())
        self.assertEqual(pub.args[0:2], ("docs", "notion-map.json"))
        self.assertTrue(pub.args[2]["prune"])

    def test_cli_trash(self):
        client = FakeClient()
        service = PageSyncService(client)
        for argv, expected in ((["trash", PARENT], "trash_page"),
                               (["trash", PARENT, "--database"], "trash_database")):
            client.calls.clear()
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(Cli(service_factory=lambda: service).run(argv), 0)
            self.assertEqual(client.calls, [(expected, PARENT)])


if __name__ == "__main__":
    unittest.main()
