import json
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import Config
from .errors import NotionApiError

API_BASE = "https://api.notion.com/v1"
RETRY_STATUSES = (429, 502, 503, 529)
MAX_ATTEMPTS = 6
APPEND_BATCH_SIZE = 100


class NotionClient:
    """Thin Notion REST client: auth, retry/backoff, and pagination."""

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

    # -- blocks --------------------------------------------------------

    def list_children(self, block_id):
        results, cursor = [], None
        while True:
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            page = self._request(
                "GET", f"/blocks/{block_id}/children?{urllib.parse.urlencode(params)}"
            )
            results += page["results"]
            if not page["has_more"]:
                return results
            cursor = page["next_cursor"]

    def append_children(self, block_id, blocks):
        for i in range(0, len(blocks), APPEND_BATCH_SIZE):
            self._request(
                "PATCH",
                f"/blocks/{block_id}/children",
                {"children": blocks[i:i + APPEND_BATCH_SIZE]},
            )

    def delete_block(self, block_id):
        self._request("DELETE", f"/blocks/{block_id}")

    # -- search --------------------------------------------------------

    def search_pages(self, query):
        res = self._request("POST", "/search", {"query": query, "page_size": 20})
        return [r for r in res["results"] if r["object"] == "page"]


def build_client(config=None):
    return NotionClient(config or Config.from_env())
