import posixpath
import re

_LINK_RE = re.compile(r"\]\((?P<target>[^)\s#]+\.md)(?:#[^)\s]*)?\)")


def notion_url(page_id):
    return "https://www.notion.so/" + page_id.replace("-", "")


class LinkRewriter:
    """Rewrites relative links between Markdown files into Notion page links.

    Links to files that are not published are left untouched.
    """

    def __init__(self, page_ids):
        self._page_ids = page_ids  # mapping: doc path -> Notion page id

    def rewrite(self, body, from_path):
        base = posixpath.dirname(from_path)

        def replace(match):
            target = match.group("target")
            if re.match(r"^[a-z][a-z0-9+.-]*:", target):  # absolute URL
                return match.group(0)
            resolved = posixpath.normpath(posixpath.join(base, target))
            page_id = self._page_ids.get(resolved)
            return f"]({notion_url(page_id)})" if page_id else match.group(0)

        return _LINK_RE.sub(replace, body)
