from .richtext import RichTextRenderer

_LIST_TYPES = ("bulleted_list_item", "numbered_list_item", "to_do", "toggle")


class MarkdownRenderer:
    """Notion block objects -> Markdown text.

    `fetch_children(block_id)` supplies nested blocks on demand, so the
    renderer has no direct dependency on the HTTP client.
    """

    def __init__(self, fetch_children, rich=None):
        self._fetch_children = fetch_children
        self._rich = rich or RichTextRenderer()

    def render(self, blocks):
        return self._render_blocks(blocks, depth=0).rstrip() + "\n"

    def _render_blocks(self, blocks, depth):
        out = []
        previous_type = None
        counter = 0
        for block in blocks:
            kind = block["type"]
            counter = counter + 1 if kind == "numbered_list_item" else 0
            text = self._render_block(block, depth, counter)
            if out:
                both_lists = kind in _LIST_TYPES and previous_type in _LIST_TYPES
                out.append("\n" if both_lists else "\n\n")
            out.append(text)
            previous_type = kind
        return "".join(out)

    def _render_block(self, block, depth, number):
        kind = block["type"]
        data = block[kind]
        indent = "    " * depth
        text = self._rich.render(data["rich_text"]) if "rich_text" in data else ""

        if kind == "paragraph":
            line = f"{indent}{text}"
        elif kind in ("heading_1", "heading_2", "heading_3"):
            line = f"{'#' * int(kind[-1])} {text}"
        elif kind in ("bulleted_list_item", "toggle"):
            line = f"{indent}- {text}"
        elif kind == "numbered_list_item":
            line = f"{indent}{number}. {text}"
        elif kind == "to_do":
            line = f"{indent}- [{'x' if data['checked'] else ' '}] {text}"
        elif kind in ("quote", "callout"):
            line = f"{indent}> {text}"
        elif kind == "code":
            language = "" if data.get("language") == "plain text" else data.get("language", "")
            body = "".join(r["plain_text"] for r in data["rich_text"])
            line = f"{indent}```{language}\n{body}\n{indent}```"
        elif kind == "divider":
            line = "---"
        elif kind == "child_page":
            return f"<!-- child page: {data['title']} -->"
        else:
            line = f"<!-- unsupported block: {kind} -->"

        if block.get("has_children"):
            children = self._render_blocks(self._fetch_children(block["id"]), depth + 1)
            line += "\n" + children
        return line
