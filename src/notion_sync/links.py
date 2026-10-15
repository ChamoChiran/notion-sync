import posixpath
import re
from pathlib import Path

# Matches `[text](target#anchor` (and images, which are skipped); the closing paren and
# any link title stay in the text after the match.
_LINK_RE = re.compile(
    r"(?P<bang>!?)\[(?P<text>[^\]]*)\]\((?P<target>[^)\s#]+)(?P<anchor>#[^)\s]*)?")
_EXTERNAL_RE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//)", re.IGNORECASE)


def notion_url(page_id):
    return "https://www.notion.so/" + page_id.replace("-", "")


class LinkRewriter:
    """Rewrites relative links between docs into links that work in Notion.

    - `x.md` becomes the Notion page of that document (a folder's landing document
      becomes the folder page; `README.md` at the top becomes the root page).
    - `folder/` becomes the Notion page of that folder.
    - Other files inside the docs folder become `source_url/<path>` when `source_url`
      is given (for example a GitHub `blob/main` URL).
    - Anything else is left as is and recorded in `warnings`, since it will be a dead
      link in Notion. Section anchors (`#heading`) are dropped: Notion cannot target them.
    """

    def __init__(self, page_ids, folder_ids=None, root_dir=None, source_url=None):
        self._page_ids = page_ids  # doc path -> Notion page id
        self._folder_ids = folder_ids or {}  # folder path -> Notion page id
        self._root_dir = Path(root_dir) if root_dir else None
        self._source_url = source_url.rstrip("/") if source_url else None
        self.warnings = []

    def rewrite(self, body, from_path):
        base = posixpath.dirname(from_path)

        def replace(match):
            target = match.group("target")
            if match.group("bang") or _EXTERNAL_RE.match(target):
                return match.group(0)
            resolved = posixpath.normpath(posixpath.join(base, target))
            url = self._resolve(resolved, target.endswith("/"))
            if url is None:
                self._warn(f"{from_path}: link to '{target}' does not resolve to a published page")
                return match.group(0)
            return f"[{match.group('text')}]({url}"

        return _LINK_RE.sub(replace, body)

    def _resolve(self, path, is_folder_link):
        if path.endswith(".md"):
            page_id = self._page_ids.get(path)
            return notion_url(page_id) if page_id else None
        if path in self._folder_ids:
            return notion_url(self._folder_ids[path])
        if is_folder_link:
            return None
        if self._source_url and self._root_dir and not path.startswith("..") \
                and (self._root_dir / path).exists():
            return f"{self._source_url}/{path}"
        return None

    def _warn(self, message):
        if message not in self.warnings:
            self.warnings.append(message)
