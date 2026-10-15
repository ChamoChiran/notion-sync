import hashlib
import json
from dataclasses import dataclass

from .documents import DocumentLoader
from .errors import ConfigError, NotionApiError
from .links import LinkRewriter
from .page_ref import PageRef
from .properties import DocsDatabaseSchema, PagePropertyBuilder
from .state import PublishState


@dataclass
class PublishReport:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    trashed: int = 0


class DocsPublisher:
    """Publishes a folder of Markdown files into a Notion database, one page per file.

    Git stays the source of truth: Notion pages are overwritten on every change.
    Unchanged files are skipped (tracked by content hash in the state file).
    """

    def __init__(self, client, loader=None):
        self._client = client
        self._loader = loader or DocumentLoader()

    def publish(self, root, state_path, parent=None, title="Docs", source_base_url=None, prune=False):
        docs = self._loader.load(root)
        state = PublishState(state_path)
        props = PagePropertyBuilder(source_base_url)
        report = PublishReport()

        self._ensure_database(state, parent, title)
        # Pass 1: make sure every page exists, so links can point at any of them.
        for doc in docs:
            self._ensure_page(state, doc, props.build(doc), report)
        state.save()

        # Pass 2: write properties and content, skipping pages that did not change.
        links = LinkRewriter(state.page_ids())
        for doc in docs:
            body = links.rewrite(doc.body, doc.path)
            self._sync_page(state, doc, props.build(doc), body, report)
            state.save()

        if prune:
            self._prune(state, {d.path for d in docs}, report)
            state.save()
        return report

    # -- steps ---------------------------------------------------------

    def _ensure_database(self, state, parent, title):
        if state.data_source_id:
            return
        if not parent:
            raise ConfigError("no database yet: pass --parent <Notion page URL> for the first run")
        db = self._client.create_database(
            PageRef.parse(parent).id, title, DocsDatabaseSchema.properties()
        )
        state.database_id = db["id"]
        state.data_source_id = db["data_sources"][0]["id"]
        state.save()

    def _ensure_page(self, state, doc, properties, report):
        if doc.path in state.pages:
            return
        page = self._client.create_page(state.data_source_id, properties)
        state.pages[doc.path] = {"id": page["id"], "hash": ""}
        report.created += 1

    def _sync_page(self, state, doc, properties, body, report):
        entry = state.pages[doc.path]
        digest = hashlib.sha256(
            json.dumps({"p": properties, "b": body}, sort_keys=True).encode()
        ).hexdigest()
        if entry["hash"] == digest:
            report.unchanged += 1
            return
        try:
            self._write(entry["id"], properties, body)
        except NotionApiError as e:
            if e.status != 404:
                raise
            # Page was deleted in Notion: recreate it and write again.
            page = self._client.create_page(state.data_source_id, properties)
            entry["id"] = page["id"]
            self._write(entry["id"], properties, body)
        entry["hash"] = digest
        report.updated += 1

    def _write(self, page_id, properties, body):
        self._client.update_page(page_id, properties=properties)
        self._client.replace_markdown(page_id, body)

    def _prune(self, state, current_paths, report):
        for path in sorted(set(state.pages) - current_paths):
            self._client.update_page(state.pages[path]["id"], in_trash=True)
            del state.pages[path]
            report.trashed += 1
