from dataclasses import dataclass

from .parser import MarkdownParser
from .renderer import MarkdownRenderer


@dataclass(frozen=True)
class PushResult:
    page_id: str
    blocks_written: int
    blocks_removed: int


@dataclass(frozen=True)
class SearchHit:
    page_id: str
    title: str
    url: str


class PageSyncService:
    """Application logic: pull a page to Markdown, push Markdown into a page."""

    def __init__(self, client, parser=None, renderer=None):
        self._client = client
        self._parser = parser or MarkdownParser()
        self._renderer = renderer or MarkdownRenderer(client.list_children)

    def pull(self, page):
        return self._renderer.render(self._client.list_children(page.id))

    def push(self, page, markdown):
        """Replace the page's content in place; the page ID and URL are unchanged."""
        blocks = self._parser.parse(markdown)
        existing = self._client.list_children(page.id)
        for block in existing:
            self._client.delete_block(block["id"])
        self._client.append_children(page.id, blocks)
        return PushResult(page.id, len(blocks), len(existing))

    def search(self, query):
        return [self._to_hit(p) for p in self._client.search_pages(query)]

    @staticmethod
    def _to_hit(page):
        title = ""
        for prop in page["properties"].values():
            if prop["type"] == "title":
                title = "".join(t["plain_text"] for t in prop["title"])
        return SearchHit(page["id"], title, page["url"])
