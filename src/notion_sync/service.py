from dataclasses import dataclass, field


@dataclass(frozen=True)
class PagePull:
    markdown: str
    truncated: bool = False
    unknown_block_ids: list = field(default_factory=list)


@dataclass(frozen=True)
class SearchHit:
    page_id: str
    title: str
    url: str


class PageSyncService:
    """Application logic: pull a page as Markdown, replace it, or patch parts of it."""

    def __init__(self, client):
        self._client = client

    def pull(self, page):
        res = self._client.get_markdown(page.id)
        return PagePull(
            markdown=res["markdown"],
            truncated=res.get("truncated", False),
            unknown_block_ids=res.get("unknown_block_ids", []),
        )

    def push(self, page, markdown, allow_deleting_content=False):
        """Replace the page body in place; the page ID and URL are unchanged."""
        self._client.replace_markdown(page.id, markdown, allow_deleting_content)

    def edit(self, page, replacements, replace_all=False):
        """Apply (old, new) text replacements without touching the rest of the page."""
        self._client.update_markdown(page.id, replacements, replace_all)

    def trash(self, ref, is_database=False):
        """Move a page or database to Notion's trash (recoverable from there)."""
        if is_database:
            self._client.trash_database(ref.id)
        else:
            self._client.trash_page(ref.id)

    def search(self, query):
        return [self._to_hit(p) for p in self._client.search_pages(query)]

    @staticmethod
    def _to_hit(page):
        title = ""
        for prop in page["properties"].values():
            if prop["type"] == "title":
                title = "".join(t["plain_text"] for t in prop["title"])
        return SearchHit(page["id"], title, page["url"])
