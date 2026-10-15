import posixpath

from .documents import folder_title
from .links import notion_url


class TableOfContents:
    """Renders a nested Markdown list of links to every published page.

    Folders list their own documents first, then their subfolders.
    """

    def __init__(self, folder_ids, page_ids):
        self._folder_ids = folder_ids  # folder path -> page id
        self._page_ids = page_ids  # doc path -> page id

    def render(self, docs):
        tree = {"docs": [], "folders": {}}
        for doc in docs:
            node = tree
            folder = ""
            directory = posixpath.dirname(doc.path)
            for part in directory.split("/") if directory else []:
                folder = f"{folder}/{part}" if folder else part
                node = node["folders"].setdefault(folder, {"docs": [], "folders": {}})
            node["docs"].append(doc)
        return "\n".join(self._lines(tree, 0))

    def _lines(self, node, depth):
        indent = "\t" * depth
        lines = []
        for doc in node["docs"]:
            lines.append(f"{indent}- [{doc.title}]({notion_url(self._page_ids[doc.path])})")
        for folder, child in node["folders"].items():
            url = notion_url(self._folder_ids[folder])
            lines.append(f"{indent}- [{folder_title(folder)}]({url})")
            lines += self._lines(child, depth + 1)
        return lines
