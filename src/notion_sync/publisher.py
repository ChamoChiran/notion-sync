import hashlib
import re
from dataclasses import dataclass, field

from . import layout
from .documents import DocumentLoader
from .errors import ConfigError, NotionApiError
from .links import LinkRewriter, notion_url
from .nav import Entry, Navigation, ancestors, split_indexes
from .page_ref import PageRef
from .state import PublishState
from .toc import TableOfContents

README_PATH = "README.md"
DEFAULT_TITLE = "Docs"
_CHILD_PAGE_RE = re.compile(r'<page\s+url="[^"]*">.*?</page>', re.DOTALL)


@dataclass
class PublishReport:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    trashed: int = 0
    warnings: list = field(default_factory=list)


@dataclass
class _Run:
    """Everything one publish needs while writing pages."""

    state: PublishState
    nav: Navigation
    sequence: list  # Entry objects in reading order, root first
    position: dict  # (kind, path) -> index in `sequence`
    root_title: str
    report: PublishReport
    links: LinkRewriter = None

    def url(self, kind, path):
        if kind == "root":
            return notion_url(self.state.root_id)
        if kind == "folder":
            return notion_url(self.state.folders[path])
        return notion_url(self.state.pages[path]["id"])

    def crumbs(self, path):
        """(title, url) for the root and each folder above `path`, root first."""
        trail = [(self.root_title, self.url("root", ""))]
        trail += [(self.nav.section(f).title, self.url("folder", f)) for f in ancestors(path)]
        return trail

    def footer(self, entry):
        i = self.position[(entry.kind, entry.path)]
        link = lambda e: (e.title, self.url(e.kind, e.path))
        previous = link(self.sequence[i - 1]) if i > 0 else None
        following = link(self.sequence[i + 1]) if i + 1 < len(self.sequence) else None
        # No separate "Docs home" link when Previous already is the home page.
        home = self.url("root", "")
        show_home = entry.kind != "root" and not (previous and previous[1] == home)
        return layout.footer(previous, following, home if show_home else None)


class DocsPublisher:
    """Publishes a folder of Markdown files as a tree of Notion pages.

    Layout in Notion mirrors the folders: one root page, one page per folder, one page
    per Markdown file. The root page's body is a table of contents followed by the
    README. A folder's `index.md` (or `README.md`) becomes the body of its folder page.
    Every page gets a breadcrumb and a Previous / Next footer that follows the reading
    order (`order` front matter, then path). Git stays the source of truth; pages are
    overwritten on change, and unchanged ones are skipped (tracked by content hash).
    """

    def __init__(self, client, loader=None):
        self._client = client
        self._loader = loader or DocumentLoader()

    def publish(self, root, state_path, parent=None, title=None, prune=False, source_url=None):
        docs = self._loader.load(root)
        readme = next((d for d in docs if d.path == README_PATH), None)
        pages, indexes = split_indexes([d for d in docs if d is not readme])
        nav = Navigation(pages, indexes)
        state = PublishState(state_path)
        report = PublishReport()

        self._ensure_root(state, parent, title)
        root_entry = Entry("root", "", state.root_title or DEFAULT_TITLE, None)
        entries = nav.entries()
        sequence = [root_entry] + entries
        run = _Run(state, nav, sequence, {(e.kind, e.path): i for i, e in enumerate(sequence)},
                   root_entry.title, report)

        # Pass 1: make sure every folder and page exists, so links can point at any of them.
        for entry in entries:
            self._ensure(state, entry, report)
        self._retire_readme_page(state, report)
        state.save()

        # Pass 2: write content, skipping pages that did not change.
        page_ids = state.page_ids()
        page_ids[README_PATH] = state.root_id  # links to the README go to the root page
        for folder, index in indexes.items():
            page_ids[index.path] = state.folders[folder]  # ...and to a folder's landing document
        run.links = LinkRewriter(page_ids, state.folders, root, source_url)
        for entry in entries:
            if entry.kind == "doc":
                self._sync_doc(run, entry)
            else:
                self._sync_folder(run, entry)
            state.save()
        self._sync_root(run, root_entry, readme)
        state.save()

        if prune:
            self._prune(state, pages, nav, report)
            state.save()
        report.warnings = run.links.warnings
        return report

    # -- structure -----------------------------------------------------

    def _ensure_root(self, state, parent, title):
        if state.root_id:
            if title:
                state.root_title = title
            return
        if not parent:
            raise ConfigError(
                "no root page yet: pass --parent <Notion page URL> (or 'workspace') for the first run"
            )
        state.root_title = title or DEFAULT_TITLE
        state.root_id = self._client.create_page(
            self._parent_object(parent), state.root_title)["id"]
        state.save()

    @staticmethod
    def _parent_object(parent):
        if parent.strip().lower() == "workspace":
            return {"type": "workspace", "workspace": True}
        return {"type": "page_id", "page_id": PageRef.parse(parent).id}

    @staticmethod
    def _page_parent(page_id):
        return {"type": "page_id", "page_id": page_id}

    @staticmethod
    def _parent_id(state, path):
        """Id of the page holding `path`: its closest folder, or the root."""
        chain = ancestors(path)
        return state.folders[chain[-1]] if chain else state.root_id

    def _ensure(self, state, entry, report):
        known = state.folders if entry.kind == "folder" else state.pages
        if entry.path in known:
            return
        page = self._client.create_page(
            self._page_parent(self._parent_id(state, entry.path)), entry.title)
        if entry.kind == "folder":
            state.folders[entry.path] = page["id"]
        else:
            state.pages[entry.path] = {"id": page["id"], "hash": ""}
        report.created += 1

    def _retire_readme_page(self, state, report):
        """The README used to be its own page; it is now the root page's body."""
        old = state.pages.pop(README_PATH, None)
        if old:
            self._client.trash_page(old["id"])
            report.trashed += 1

    # -- content -------------------------------------------------------

    def _sync_doc(self, run, entry):
        doc, state = entry.obj, run.state
        page = state.pages[doc.path]
        text = layout.join_blocks(
            layout.breadcrumb(run.crumbs(doc.path)),
            layout.summary(doc.meta),
            layout.TOC_BLOCK if layout.wants_toc(doc.body) else "",
            run.links.rewrite(doc.body, doc.path),
            run.footer(entry),
        )
        digest = self._digest(doc.title, text)
        if page["hash"] == digest:
            run.report.unchanged += 1
            return
        try:
            self._write(page["id"], doc.title, text)
        except NotionApiError as e:
            if e.status != 404:
                raise
            # Page was deleted in Notion: recreate it and write again.
            parent = self._page_parent(self._parent_id(state, doc.path))
            page["id"] = self._client.create_page(parent, doc.title)["id"]
            self._write(page["id"], doc.title, text)
        page["hash"] = digest
        run.report.updated += 1

    def _sync_folder(self, run, entry):
        section, state = entry.obj, run.state
        index = section.index
        listing = [f"- [{d.title}]({run.url('doc', d.path)})" for d in section.docs]
        listing += [f"- [{s.title}]({run.url('folder', s.path)})" for s in section.sections]
        text = layout.join_blocks(
            layout.breadcrumb(run.crumbs(section.path)),
            layout.summary(index.meta) if index else "",
            run.links.rewrite(index.body, index.path) if index else "",
            "## In this section\n\n" + "\n".join(listing),
            run.footer(entry),
        )
        digest = self._digest(entry.title, text)
        if state.folder_hashes.get(section.path) == digest:
            run.report.unchanged += 1
            return
        self._write(state.folders[section.path], entry.title, text, keep_children=True)
        state.folder_hashes[section.path] = digest
        run.report.updated += 1

    def _sync_root(self, run, entry, readme):
        """Root body: 'Table of contents' heading, the contents list, then the README."""
        state = run.state
        blocks = ["## Table of contents", TableOfContents(run.nav, run.url).render()]
        if readme:
            blocks.append(f"## {readme.title}\n\n" + run.links.rewrite(readme.body, readme.path).strip())
        blocks.append(run.footer(entry))
        text = layout.join_blocks(*blocks)
        digest = self._digest(state.root_title, text)
        if state.root_hash == digest:
            run.report.unchanged += 1
            return
        # An unknown title (state from an older version, no --title given) is left alone.
        self._write(state.root_id, state.root_title or None, text, keep_children=True)
        state.root_hash = digest
        run.report.updated += 1

    @staticmethod
    def _digest(title, text):
        return hashlib.sha256(f"{title}\n{text}".encode()).hexdigest()

    def _write(self, page_id, title, text, keep_children=False):
        if keep_children:
            # Replacing the body would delete the page's child pages, so read their tags
            # back and keep them in the new text.
            current = self._client.get_markdown(page_id)["markdown"]
            children = _CHILD_PAGE_RE.findall(current)
            if children:
                text = text.rstrip("\n") + "\n\n" + "\n".join(children) + "\n"
        self._client.set_title(page_id, title)  # also picks up a renamed title
        self._client.replace_markdown(page_id, text)

    def _prune(self, state, pages, nav, report):
        current = {d.path for d in pages}
        needed_folders = set(self._folder_paths(nav.root))
        for path in sorted(set(state.pages) - current):
            self._client.trash_page(state.pages[path]["id"])
            del state.pages[path]
            report.trashed += 1
        # Deepest first, so a folder is never trashed before its subfolders.
        for folder in sorted(set(state.folders) - needed_folders, reverse=True):
            self._client.trash_page(state.folders[folder])
            del state.folders[folder]
            state.folder_hashes.pop(folder, None)
            report.trashed += 1

    def _folder_paths(self, section):
        for child in section.sections:
            yield child.path
            yield from self._folder_paths(child)
