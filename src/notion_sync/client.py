import json
import time
import urllib.error
import urllib.request

from .config import Config
from .errors import NotionApiError

API_BASE = "https://api.notion.com/v1"
RETRY_STATUSES = (429, 500, 502, 503, 504, 529)
MAX_ATTEMPTS = 6


class NotionClient:
    """Notion REST client for the page Markdown endpoints, search and auth.

    Handles auth headers and retry/backoff on rate limits and server errors.
    """

    def __init__(self, config, opener=urllib.request.urlopen, sleep=time.sleep):
        self._config = config
        self._open = opener
        self._sleep = sleep

    # -- transport -----------------------------------------------------

    def _request(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            req = urllib.request.Request(
                API_BASE + path,
                data=data,
                method=method,
                headers={
                    "Authorization": f"Bearer {self._config.token}",
                    "Notion-Version": self._config.notion_version,
                    "Content-Type": "application/json",
                },
            )
            try:
                with self._open(req) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                if e.code in RETRY_STATUSES and attempt < MAX_ATTEMPTS:
                    self._sleep(float(e.headers.get("Retry-After", 2 ** (attempt - 1))))
                    continue
                raise NotionApiError(
                    e.code, method, path, e.read().decode(errors="replace")
                ) from None

    # -- page markdown -------------------------------------------------

    def get_markdown(self, page_id):
        """Return the raw `page_markdown` object for a page (or an unknown block ID)."""
        return self._request("GET", f"/pages/{page_id}/markdown")

    def replace_markdown(self, page_id, markdown, allow_deleting_content=False):
        body = {
            "type": "replace_content",
            "replace_content": {"new_str": markdown},
        }
        if allow_deleting_content:
            body["replace_content"]["allow_deleting_content"] = True
        return self._request("PATCH", f"/pages/{page_id}/markdown", body)

    def update_markdown(self, page_id, replacements, replace_all_matches=False):
        """Apply search-and-replace edits. `replacements` is a list of (old, new) pairs."""
        updates = []
        for old, new in replacements:
            update = {"old_str": old, "new_str": new}
            if replace_all_matches:
                update["replace_all_matches"] = True
            updates.append(update)
        body = {"type": "update_content", "update_content": {"content_updates": updates}}
        return self._request("PATCH", f"/pages/{page_id}/markdown", body)

    # -- search --------------------------------------------------------

    def search_pages(self, query):
        res = self._request("POST", "/search", {"query": query, "page_size": 20})
        return [r for r in res["results"] if r["object"] == "page"]


def build_client(config=None):
    return NotionClient(config or Config.from_env())
