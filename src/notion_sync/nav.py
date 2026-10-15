import posixpath
from collections import namedtuple

from .documents import folder_title

INDEX_NAMES = ("index.md", "readme.md")  # a folder's landing page, in order of preference
UNORDERED = float("inf")

# kind is "root", "folder" or "doc"; obj is the Section or Document behind it.
Entry = namedtuple("Entry", "kind path title obj")


def split_indexes(docs):
    """Separate folder landing documents (index.md, else README.md) from regular pages."""
    chosen = {}
    for doc in docs:
        folder, name = posixpath.split(doc.path)
        rank = INDEX_NAMES.index(name.lower()) if name.lower() in INDEX_NAMES else None
        if not folder or rank is None:
            continue
        if folder not in chosen or rank < chosen[folder][0]:
            chosen[folder] = (rank, doc)
    indexes = {folder: doc for folder, (_, doc) in chosen.items()}
    used = {doc.path for doc in indexes.values()}
    return [d for d in docs if d.path not in used], indexes


def ancestors(path):
    """Folder paths from the top down that contain `path`, e.g. ['a', 'a/b'] for 'a/b/x.md'."""
    directory = posixpath.dirname(path)
    parts = directory.split("/") if directory else []
    return ["/".join(parts[:i + 1]) for i in range(len(parts))]


def _order_key(order, path):
    return (UNORDERED if order is None else order, path.lower())


class Section:
    """A folder in the docs tree: its landing document (if any), documents and subfolders."""

    def __init__(self, path):
        self.path = path
        self.index = None
        self.docs = []
        self.sections = []

    @property
    def title(self):
        return self.index.title if self.index else folder_title(self.path)

    @property
    def order(self):
        return self.index.order if self.index else None


class Navigation:
    """The docs tree in reading order.

    Within a folder: documents first, then subfolders. Both are sorted by the `order`
    front matter value (a folder takes it from its landing document), then by path.
    """

    def __init__(self, pages, indexes):
        self.root = Section("")
        self._by_path = {"": self.root}
        for doc in pages:
            self._ensure(posixpath.dirname(doc.path)).docs.append(doc)
        for folder, doc in indexes.items():
            self._ensure(folder).index = doc
        self._sort(self.root)

    def _ensure(self, path):
        if path not in self._by_path:
            parent = self._ensure(posixpath.dirname(path))
            self._by_path[path] = Section(path)
            parent.sections.append(self._by_path[path])
        return self._by_path[path]

    def _sort(self, section):
        section.docs.sort(key=lambda d: _order_key(d.order, d.path))
        section.sections.sort(key=lambda s: _order_key(s.order, s.path))
        for child in section.sections:
            self._sort(child)

    def section(self, path):
        return self._by_path[path]

    def entries(self):
        """Every folder and document in reading order (the root page comes before these)."""
        return list(self._walk(self.root))

    def _walk(self, section):
        for doc in section.docs:
            yield Entry("doc", doc.path, doc.title, doc)
        for child in section.sections:
            yield Entry("folder", child.path, child.title, child)
            yield from self._walk(child)
