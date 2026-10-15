import re

TEXT_LIMIT = 2000  # Notion max characters per rich-text item


def chunk_text(text, limit=TEXT_LIMIT):
    return [text[i:i + limit] for i in range(0, len(text), limit)]


class InlineParser:
    """Markdown inline syntax -> Notion rich_text array."""

    _PATTERN = re.compile(
        r"(\[(?P<ltext>[^\]]+)\]\((?P<url>[^)\s]+)\))"
        r"|(`(?P<code>[^`]+)`)"
        r"|(\*\*(?P<bold>.+?)\*\*)"
        r"|(~~(?P<strike>.+?)~~)"
        r"|(\*(?P<ital1>[^*\s][^*]*?)\*)"
        r"|(?<!\w)(_(?P<ital2>[^_\s][^_]*?)_)(?!\w)"
    )

    def parse(self, text):
        rich = []
        pos = 0
        for m in self._PATTERN.finditer(text):
            self._add(rich, text[pos:m.start()])
            if m.group("ltext"):
                self._add(rich, m.group("ltext"), link=m.group("url"))
            elif m.group("code"):
                self._add(rich, m.group("code"), {"code": True})
            elif m.group("bold"):
                self._add(rich, m.group("bold"), {"bold": True})
            elif m.group("strike"):
                self._add(rich, m.group("strike"), {"strikethrough": True})
            else:
                self._add(rich, m.group("ital1") or m.group("ital2"), {"italic": True})
            pos = m.end()
        self._add(rich, text[pos:])
        return rich

    @staticmethod
    def _add(rich, content, annotations=None, link=None):
        for chunk in chunk_text(content):
            item = {"type": "text", "text": {"content": chunk}}
            if link:
                item["text"]["link"] = {"url": link}
            if annotations:
                item["annotations"] = annotations
            rich.append(item)

    @staticmethod
    def plain(text):
        """Rich text with no formatting (used for code blocks)."""
        return [{"type": "text", "text": {"content": c}} for c in chunk_text(text)]


class RichTextRenderer:
    """Notion rich_text array -> Markdown inline syntax."""

    def render(self, rich):
        return "".join(self._render_item(r) for r in rich)

    @staticmethod
    def _render_item(item):
        text = item.get("plain_text", "")
        if not text.strip():
            return text
        lead = text[: len(text) - len(text.lstrip())]
        trail = text[len(text.rstrip()):]
        core = text.strip()
        ann = item.get("annotations", {})
        if ann.get("code"):
            core = f"`{core}`"
        if ann.get("bold"):
            core = f"**{core}**"
        if ann.get("italic"):
            core = f"*{core}*"
        if ann.get("strikethrough"):
            core = f"~~{core}~~"
        if item.get("href"):
            core = f"[{core}]({item['href']})"
        return lead + core + trail
