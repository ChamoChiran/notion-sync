import re
from dataclasses import dataclass, field
from pathlib import Path

_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Document:
    """A Markdown file prepared for publishing.

    `path` is the POSIX-style path relative to the docs root. `body` has the front
    matter removed, and the first H1 removed when it was used as the title (Notion
    shows the title as the page name, so keeping it would duplicate it).
    """

    path: str
    title: str
    body: str
    meta: dict = field(default_factory=dict)


class FrontMatterParser:
    """Splits `---` delimited front matter (flat `key: value` lines) from Markdown."""

    def parse(self, text):
        text = text.replace("\r\n", "\n")
        if not text.startswith("---\n"):
            return {}, text
        end = text.find("\n---", 4)
        if end == -1:
            return {}, text
        block, rest = text[4:end], text[end + 4:]
        meta = {}
        for line in block.split("\n"):
            if ":" not in line or line.lstrip().startswith("#"):
                continue
            key, _, value = line.partition(":")
            meta[self._normalize_key(key)] = value.strip().strip("\"'")
        return meta, rest.lstrip("\n")

    @staticmethod
    def _normalize_key(key):
        return re.sub(r"[\s-]+", "_", key.strip().lower())


class DocumentLoader:
    """Finds Markdown files under a root and turns them into Documents."""

    def __init__(self, parser=None):
        self._parser = parser or FrontMatterParser()

    def load(self, root):
        root = Path(root)
        found = []
        for file in root.rglob("*.md"):
            rel = file.relative_to(root)
            if not any(part.startswith(".") for part in rel.parts):
                found.append((file, rel.as_posix()))
        # Deterministic on every OS: top-level files first, then folders, alphabetical.
        found.sort(key=lambda item: ("/" in item[1], item[1].lower()))
        return [self._load_one(file, rel) for file, rel in found]

    def _load_one(self, file, rel_path):
        meta, body = self._parser.parse(file.read_text(encoding="utf-8"))
        title = meta.get("title")
        if not title:
            match = _H1_RE.search(body)
            if match:
                title = match.group(1)
                body = body[:match.start()] + body[match.end():].lstrip("\n")
            else:
                title = Path(rel_path).stem.replace("-", " ")
        return Document(path=rel_path, title=title, body=body.strip() + "\n", meta=meta)
