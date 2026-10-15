import hashlib
import posixpath
from dataclasses import dataclass

from .documents import DocumentLoader
from .errors import ConfigError, NotionApiError
from .links import LinkRewriter
from .page_ref import PageRef
from .state import PublishState

_META_LABELS = (
    ("status", "Status"),
    ("owner", "Owner"),
    ("component", "Component"),
    ("last_reviewed", "Last reviewed"),
)


@dataclass
class PublishReport:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    trashed: int = 0


class DocsPublisher:
    """Publishes a folder of Markdown files as a tree of Notion pages.

    Layout in Notion mirrors the folders: one root page, one page per folder, one page
    per Markdown file. Git stays the source of truth; pages are overwritten on change,
    and unchanged files are skipped (tracked by content hash in the state file).
    """

    def __init__(self, client, loader=None):
        self._client = client
        self._loader = loader or DocumentLoader()

    def publish(self, root, state_path, parent=None, title="Docs", prune=False):
        docs = self._loader.load(root)
        state = PublishState(state_path)
        report = PublishReport()

        self._ensure_root(state, parent, title)
        # Pass 1: create every folder and page, so links can point at any of them.
        for doc in docs:
            self._ensure_page(state, doc, report)
        state.save()

        # Pass 2: write content, skipping pages that did not change.
        links = LinkRewriter(state.page_ids())
        for doc in docs:
            body = self._header(doc) + links.rewrite(doc.body, doc.path)
            self._sync_page(state, doc, body, report)
            state.save()

        if prune:
            self._prune(state, docs, report)
            state.save()
        return report

    # -- structure -----------------------------------------------------

    def _ensure_root(self, state, parent, title):
        if state.root_id:
            return
        if not parent:
            raise ConfigError(
                "no root page yet: pass --parent <Notion page URL> (or 'workspace') for the first run"
            )
        state.root_id = self._client.create_page(self._parent_object(parent), f"# {title}\n")["id"]
        state.save()

    @staticmethod
    def _parent_object(parent):
        if parent.strip().lower() == "workspace":
            return {"type": "workspace", "workspace": True}
        return {"type": "page_id", "page_id": PageRef.parse(parent).id}

    @staticmethod
    def _page_parent(page_id):
        return {"type": "page_id", "page_id": page_id}

    def _folder_chain(self, doc_path):
        """Folder paths from the top down for a doc, e.g. ['a', 'a/b'] for 'a/b/x.md'."""
        parts = posixpath.dirname(doc_path).split("/") if "/" in doc_path else []
        return ["/".join(parts[:i + 1]) for i in range(len(parts))]

    def _parent_for(self, state, doc_path):
        chain = self._folder_chain(doc_path)
        return state.folders[chain[-1]] if chain else state.root_id

    def _ensure_page(self, state, doc, report):
        parent_id = state.root_id
        for folder in self._folder_chain(doc.path):
            if folder not in state.folders:
                name = posixpath.basename(folder).replace("-", " ").replace("_", " ").title()
                state.folders[folder] = self._client.create_page(
                    self._page_parent(parent_id), f"# {name}\n")["id"]
                report.created += 1
            parent_id = state.folders[folder]
        if doc.path not in state.pages:
            page = self._client.create_page(self._page_parent(parent_id), f"# {doc.title}\n")
            state.pages[doc.path] = {"id": page["id"], "hash": ""}
            report.created += 1

    # -- content -------------------------------------------------------

    @staticmethod
    def _header(doc):
        """A one-line summary of the front matter, since pages have no properties."""
        parts = [f"**{label}:** {doc.meta[key]}" for key, label in _META_LABELS if doc.meta.get(key)]
        return ("> " + " · ".join(parts) + "\n\n") if parts else ""

    def _sync_page(self, state, doc, body, report):
        entry = state.pages[doc.path]
        digest = hashlib.sha256(body.encode()).hexdigest()
        if entry["hash"] == digest:
            report.unchanged += 1
            return
        try:
            self._client.replace_markdown(entry["id"], body)
        except NotionApiError as e:
            if e.status != 404:
                raise
            # Page was deleted in Notion: recreate it and write again.
            parent_id = self._parent_for(state, doc.path)
            entry["id"] = self._client.create_page(
                self._page_parent(parent_id), f"# {doc.title}\n")["id"]
            self._client.replace_markdown(entry["id"], body)
        entry["hash"] = digest
        report.updated += 1

    def _prune(self, state, docs, report):
        current = {d.path for d in docs}
        needed_folders = {f for d in docs for f in self._folder_chain(d.path)}
        for path in sorted(set(state.pages) - current):
            self._client.trash_page(state.pages[path]["id"])
            del state.pages[path]
            report.trashed += 1
        # Deepest first, so a folder is never trashed before its subfolders.
        for folder in sorted(set(state.folders) - needed_folders, reverse=True):
            self._client.trash_page(state.folders[folder])
            del state.folders[folder]
            report.trashed += 1
