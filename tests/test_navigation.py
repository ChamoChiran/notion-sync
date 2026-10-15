import json
import tempfile
import unittest
from pathlib import Path

from notion_sync.documents import Document
from notion_sync.layout import callout, footer, wants_toc
from notion_sync.links import LinkRewriter, notion_url
from notion_sync.nav import Navigation, split_indexes
from notion_sync.publisher import DocsPublisher
from notion_sync.state import PublishState
from test_publish import PARENT, FakeClient


def url(page_id):
    return notion_url(page_id)


class SplitIndexTests(unittest.TestCase):
    def test_index_beats_readme_and_top_level_readme_is_ignored(self):
        docs = [Document("README.md", "Top", "", {}),
                Document("a/README.md", "Readme", "", {}),
                Document("a/index.md", "Index", "", {}),
                Document("a/x.md", "X", "", {}),
                Document("b/README.md", "B", "", {})]
        pages, indexes = split_indexes(docs)
        self.assertEqual({k: v.path for k, v in indexes.items()}, {"a": "a/index.md", "b": "b/README.md"})
        self.assertEqual([d.path for d in pages], ["README.md", "a/README.md", "a/x.md"])


class NavigationTests(unittest.TestCase):
    def test_order_front_matter_then_path_and_folders_last(self):
        docs = [Document("z.md", "Z", "", {}),
                Document("a/b.md", "B", "", {}),
                Document("a/a.md", "A", "", {"order": "5"}),
                Document("a/c.md", "C", "", {"order": "1"}),
                Document("m/x.md", "X", "", {})]
        indexes = {"m": Document("m/index.md", "M", "", {"order": "0"})}
        nav = Navigation(docs, indexes)
        self.assertEqual([(e.kind, e.path) for e in nav.entries()], [
            ("doc", "z.md"),
            ("folder", "m"), ("doc", "m/x.md"),  # index order 0 puts folder m before a
            ("folder", "a"), ("doc", "a/c.md"), ("doc", "a/a.md"), ("doc", "a/b.md"),
        ])

    def test_non_numeric_order_is_ignored(self):
        self.assertIsNone(Document("a.md", "A", "", {"order": "soon"}).order)


class LayoutTests(unittest.TestCase):
    def test_callout_colour_follows_status(self):
        self.assertIn('icon="🟢" color="green_bg"', callout({"status": "Accepted"}))
        self.assertIn('icon="🔴" color="red_bg"', callout({"status": "Deprecated"}))
        self.assertIn('icon="📝" color="gray_bg"', callout({"owner": "Me"}))
        self.assertEqual(callout({"title": "x"}), "")

    def test_footer_parts(self):
        self.assertEqual(footer(("P", "u1"), ("N", "u2"), "h"),
                         "---\n\n← [P](u1) | [Docs home](h) | [N](u2) →")
        self.assertEqual(footer(None, ("N", "u2")), "---\n\n[N](u2) →")
        self.assertEqual(footer(None, None), "")

    def test_toc_needs_three_headings_outside_code(self):
        self.assertFalse(wants_toc("## a\n\n## b\n"))
        self.assertTrue(wants_toc("## a\n\n### b\n\n## c\n"))
        self.assertFalse(wants_toc("## a\n\n```\n## x\n## y\n```\n"))


class LinkResolutionTests(unittest.TestCase):
    def test_folder_links_and_repo_files_and_warnings(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "scripts").mkdir()
            (Path(d) / "scripts" / "run.sh").write_text("x", encoding="utf-8")
            rw = LinkRewriter({"a/x.md": "p1"}, {"a": "f1"}, d, "https://git.example/blob/main/")
            text = ("[f](../a/) [g](../a) [s](../scripts/run.sh#L3) [bad](nope.md) [dir](../zzz/) "
                    "![img](pic.png) [ext](https://e.com/x.md) [anchor](#top)")
            out = rw.rewrite(text, "b/y.md")
        self.assertIn("[f](https://www.notion.so/f1)", out)
        self.assertIn("[g](https://www.notion.so/f1)", out)
        self.assertIn("[s](https://git.example/blob/main/scripts/run.sh)", out)
        self.assertIn("![img](pic.png)", out)  # images are not links
        self.assertIn("[ext](https://e.com/x.md) [anchor](#top)", out)
        self.assertEqual(sorted(rw.warnings), [
            "b/y.md: link to '../zzz/' does not resolve to a published page",
            "b/y.md: link to 'nope.md' does not resolve to a published page",
        ])

    def test_repo_file_link_left_alone_without_source_url(self):
        rw = LinkRewriter({}, {}, ".", None)
        self.assertEqual(rw.rewrite("[s](run.sh)", "a.md"), "[s](run.sh)")
        self.assertEqual(len(rw.warnings), 1)


class PublishNavigationTests(unittest.TestCase):
    def make_root(self, d):
        root = Path(d) / "docs"
        (root / "guide").mkdir(parents=True)
        (root / "README.md").write_text("# Home\n\nwelcome\n", encoding="utf-8")
        (root / "intro.md").write_text("# Intro\n\nsee [guide](guide/)\n", encoding="utf-8")
        (root / "guide" / "index.md").write_text(
            "---\nicon: 🧭\n---\n\n# The Guide\n\nStart here, then [two](two.md).\n", encoding="utf-8")
        (root / "guide" / "one.md").write_text("---\norder: 1\n---\n\n# One\n\ntext\n", encoding="utf-8")
        (root / "guide" / "two.md").write_text("---\norder: 2\n---\n\n# Two\n\n[home](../README.md)\n",
                                               encoding="utf-8")
        return root

    def publish(self, d, client=None, **kw):
        client = client or FakeClient()
        root, state = self.make_root(d), Path(d) / "map.json"
        report = DocsPublisher(client).publish(root, state, parent=PARENT, title="Book", **kw)
        saved = json.loads(state.read_text(encoding="utf-8"))
        bodies = {c[1]: c[2] for c in client.calls if c[0] == "replace"}
        return client, saved, bodies, report

    def test_prev_next_chain_follows_reading_order(self):
        with tempfile.TemporaryDirectory() as d:
            client, saved, bodies, _ = self.publish(d)
        root, guide = saved["root_id"], saved["folders"]["guide"]
        pid = lambda p: saved["pages"][p]["id"]
        # reading order: root -> Intro -> The Guide (folder) -> One -> Two
        self.assertTrue(bodies[pid("intro.md")].rstrip().endswith(
            "---\n\n← [Book](%s) | [The Guide](%s) →" % (url(root), url(guide))))
        self.assertTrue(bodies[pid("guide/one.md")].rstrip().endswith(
            "---\n\n← [The Guide](%s) | [Docs home](%s) | [Two](%s) →"
            % (url(guide), url(root), url(pid("guide/two.md")))))
        last = bodies[pid("guide/two.md")].rstrip()
        self.assertTrue(last.endswith("← [One](%s) | [Docs home](%s)" % (url(pid("guide/one.md")), url(root))))
        # the root has no Previous; its child-page tags follow the footer
        self.assertIn("---\n\n[Intro](%s) →" % url(pid("intro.md")), bodies[root])

    def test_breadcrumbs(self):
        with tempfile.TemporaryDirectory() as d:
            client, saved, bodies, _ = self.publish(d)
        root, guide = saved["root_id"], saved["folders"]["guide"]
        self.assertTrue(bodies[saved["pages"]["guide/one.md"]["id"]].startswith(
            "[Book](%s) / [The Guide](%s)\n" % (url(root), url(guide))))
        self.assertTrue(bodies[guide].startswith("[Book](%s)\n" % url(root)))
        self.assertTrue(bodies[saved["pages"]["intro.md"]["id"]].startswith("[Book](%s)\n" % url(root)))

    def test_folder_landing_page_uses_index_and_lists_children(self):
        with tempfile.TemporaryDirectory() as d:
            client, saved, bodies, _ = self.publish(d)
        guide = saved["folders"]["guide"]
        body = bodies[guide]
        self.assertIn("Start here, then [two](%s)." % url(saved["pages"]["guide/two.md"]["id"]), body)
        self.assertIn("## In this section\n\n- [One](%s)\n- [Two](%s)" % (
            url(saved["pages"]["guide/one.md"]["id"]), url(saved["pages"]["guide/two.md"]["id"])), body)
        self.assertEqual(client.titles[guide], "The Guide")
        self.assertEqual(client.icons[guide], "🧭")
        self.assertNotIn("guide/index.md", saved["pages"])  # no page of its own
        # intro links to the folder page, not a dead relative path
        self.assertIn("(%s)" % url(guide), bodies[saved["pages"]["intro.md"]["id"]])

    def test_folder_page_keeps_its_children_when_rewritten(self):
        with tempfile.TemporaryDirectory() as d:
            client = FakeClient()
            self.publish(d, client)
            state = PublishState(Path(d) / "map.json")
            guide = state.folders["guide"]
            # Notion reports the child pages of the folder page
            client.children[guide] = [state.pages["guide/one.md"]["id"]]
            (Path(d) / "docs" / "guide" / "index.md").write_text("# The Guide\n\nnew\n", encoding="utf-8")
            client.calls.clear()
            DocsPublisher(client).publish(Path(d) / "docs", Path(d) / "map.json")
            body = {c[1]: c[2] for c in client.calls if c[0] == "replace"}[guide]
        one = state.pages["guide/one.md"]["id"].replace("-", "")
        self.assertTrue(body.rstrip().endswith('<page url="https://www.notion.so/%s">One</page>' % one))

    def test_icons_default_by_section_and_doc(self):
        with tempfile.TemporaryDirectory() as d:
            client, saved, _, _ = self.publish(d)
        self.assertEqual(client.icons[saved["root_id"]], "📚")
        self.assertEqual(client.icons[saved["pages"]["intro.md"]["id"]], "📄")

    def test_toc_block_only_on_long_pages(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.make_root(d)
            (root / "guide" / "two.md").write_text(
                "---\norder: 2\n---\n\n# Two\n\n## a\n\n## b\n\n### c\n", encoding="utf-8")
            client = FakeClient()
            DocsPublisher(client).publish(root, Path(d) / "map.json", parent=PARENT)
            saved = json.loads((Path(d) / "map.json").read_text(encoding="utf-8"))
            bodies = {c[1]: c[2] for c in client.calls if c[0] == "replace"}
        self.assertIn("<table_of_contents/>", bodies[saved["pages"]["guide/two.md"]["id"]])
        self.assertNotIn("<table_of_contents/>", bodies[saved["pages"]["guide/one.md"]["id"]])

    def test_reordering_rewrites_only_affected_pages(self):
        with tempfile.TemporaryDirectory() as d:
            self.publish(d)
            (Path(d) / "docs" / "guide" / "two.md").write_text(
                "---\norder: 0\n---\n\n# Two\n\n[home](../README.md)\n", encoding="utf-8")
            client = FakeClient()
            client.children[PublishState(Path(d) / "map.json").folders["guide"]] = []
            report = DocsPublisher(client).publish(Path(d) / "docs", Path(d) / "map.json")
        # Two (now first), One (its Previous changed), the folder listing, the root contents
        self.assertEqual((report.updated, report.unchanged), (4, 1))

    def test_unresolved_links_are_reported(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.make_root(d)
            (root / "intro.md").write_text("# Intro\n\n[x](missing.md)\n", encoding="utf-8")
            report = DocsPublisher(FakeClient()).publish(root, Path(d) / "map.json", parent=PARENT)
        self.assertEqual(report.warnings,
                         ["intro.md: link to 'missing.md' does not resolve to a published page"])

    def test_old_state_without_new_keys_still_loads_and_keeps_pages(self):
        with tempfile.TemporaryDirectory() as d:
            client, saved, _, _ = self.publish(d)
            state = Path(d) / "map.json"
            for key in ("root_title", "folder_hashes"):
                saved.pop(key)
            state.write_text(json.dumps(saved), encoding="utf-8")
            client2 = FakeClient()
            client2.children[saved["folders"]["guide"]] = []
            DocsPublisher(client2).publish(Path(d) / "docs", state)  # no --title, no --parent
        self.assertEqual([c for c in client2.calls if c[0] == "create_page"], [])
        # unknown root title: crumbs fall back to "Docs" and the root is not renamed
        self.assertNotIn(("set_title", saved["root_id"], "Docs"), client2.calls)


if __name__ == "__main__":
    unittest.main()
