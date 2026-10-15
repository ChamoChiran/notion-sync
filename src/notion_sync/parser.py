import re

from .richtext import InlineParser

_LIST_RE = re.compile(r"^(?P<indent>[ \t]*)(?:(?P<bullet>[-*+])|(?P<num>\d+)\.)\s+(?P<body>.*)$")
_TODO_RE = re.compile(r"^\[(?P<checked>[ xX])\]\s+(?P<body>.*)$")
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
_DIVIDER_RE = re.compile(r"(-{3,}|\*{3,}|_{3,})")


def _indent_width(text):
    return len(text.replace("\t", "    "))


class _ParseState:
    """Mutable state for a single parse: output blocks, open lists, pending paragraph."""

    def __init__(self):
        self.root = []
        self.list_stack = []  # (indent_width, block)
        self.paragraph = []

    def end_lists(self):
        self.list_stack.clear()

    def add_block(self, block):
        self.end_lists()
        self.root.append(block)

    def add_list_item(self, block, indent):
        while self.list_stack and self.list_stack[-1][0] >= indent:
            self.list_stack.pop()
        if self.list_stack:
            parent = self.list_stack[-1][1]
            parent[parent["type"]].setdefault("children", []).append(block)
        else:
            self.root.append(block)
        self.list_stack.append((indent, block))


class MarkdownParser:
    """Markdown text -> list of Notion block objects.

    Supports headings (1-3), paragraphs, bulleted/numbered/to-do lists with
    nesting, block quotes, fenced code, dividers, and inline formatting.
    """

    def __init__(self, inline=None):
        self._inline = inline or InlineParser()

    def parse(self, markdown):
        state = _ParseState()
        lines = markdown.replace("\r\n", "\n").split("\n")
        i = 0
        while i < len(lines):
            i = self._consume(lines, i, state)
        self._flush_paragraph(state)
        return state.root

    # -- line handling -------------------------------------------------

    def _consume(self, lines, i, state):
        """Handle the construct starting at lines[i]; return the next index."""
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            self._flush_paragraph(state)
            return self._code_fence(lines, i, state)
        if not stripped:
            self._flush_paragraph(state)
        elif stripped.startswith("<!--") and stripped.endswith("-->"):
            pass  # placeholder emitted by pull for unsupported blocks
        elif _DIVIDER_RE.fullmatch(stripped):
            self._flush_paragraph(state)
            state.add_block({"type": "divider", "divider": {}})
        elif _HEADING_RE.match(stripped):
            self._flush_paragraph(state)
            hashes, body = _HEADING_RE.match(stripped).groups()
            kind = f"heading_{len(hashes)}"
            state.add_block({"type": kind, kind: {"rich_text": self._inline.parse(body)}})
        elif stripped.startswith(">"):
            self._flush_paragraph(state)
            body = stripped.lstrip(">").strip()
            state.add_block({"type": "quote", "quote": {"rich_text": self._inline.parse(body)}})
        elif _LIST_RE.match(line):
            self._flush_paragraph(state)
            self._list_item(_LIST_RE.match(line), state)
        else:
            state.end_lists()
            state.paragraph.append(stripped)
        return i + 1

    def _code_fence(self, lines, i, state):
        language = lines[i].strip()[3:].strip() or "plain text"
        code = []
        i += 1
        while i < len(lines) and not lines[i].strip().startswith("```"):
            code.append(lines[i])
            i += 1
        state.add_block({
            "type": "code",
            "code": {"rich_text": self._inline.plain("\n".join(code)), "language": language},
        })
        return i + 1  # skip closing fence

    def _list_item(self, match, state):
        body = match.group("body")
        todo = _TODO_RE.match(body) if match.group("bullet") else None
        if todo:
            block = {"type": "to_do", "to_do": {
                "rich_text": self._inline.parse(todo.group("body")),
                "checked": todo.group("checked").lower() == "x",
            }}
        elif match.group("bullet"):
            block = {"type": "bulleted_list_item",
                     "bulleted_list_item": {"rich_text": self._inline.parse(body)}}
        else:
            block = {"type": "numbered_list_item",
                     "numbered_list_item": {"rich_text": self._inline.parse(body)}}
        state.add_list_item(block, _indent_width(match.group("indent")))

    def _flush_paragraph(self, state):
        if state.paragraph:
            state.root.append({
                "type": "paragraph",
                "paragraph": {"rich_text": self._inline.parse(" ".join(state.paragraph))},
            })
            state.paragraph.clear()
