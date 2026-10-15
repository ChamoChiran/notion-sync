class TableOfContents:
    """Renders a nested Markdown list of links to every published page.

    Folders list their own documents first, then their subfolders, in reading order.
    """

    def __init__(self, navigation, url_for):
        self._nav = navigation
        self._url_for = url_for  # (kind, path) -> page url

    def render(self):
        return "\n".join(self._lines(self._nav.root, 0))

    def _lines(self, section, depth):
        indent = "\t" * depth
        lines = []
        for doc in section.docs:
            lines.append(f"{indent}- [{doc.title}]({self._url_for('doc', doc.path)})")
        for child in section.sections:
            lines.append(f"{indent}- [{child.title}]({self._url_for('folder', child.path)})")
            lines += self._lines(child, depth + 1)
        return lines
