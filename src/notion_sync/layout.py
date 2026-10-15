"""Page furniture around a document's body: breadcrumb, status callout, footer, icons."""
import posixpath
import re

ROOT_ICON = "📚"
DOC_ICON = "📄"
FOLDER_ICON = "📁"
SECTION_ICONS = {
    "architecture": "🏗️", "onboarding": "🚀", "runbooks": "📟", "policies": "📜",
    "templates": "🧩", "decisions": "⚖️", "components": "🧱", "flows": "🔀",
}
TOC_BLOCK = "<table_of_contents/>"
_TOC_MIN_HEADINGS = 3

_META_LABELS = (
    ("status", "Status"),
    ("owner", "Owner"),
    ("component", "Component"),
    ("last_reviewed", "Last reviewed"),
)
_STATUS_STYLES = (
    (("draft", "proposed", "wip"), ("🟡", "yellow_bg")),
    (("accepted", "active", "approved", "final", "stable"), ("🟢", "green_bg")),
    (("deprecated", "superseded", "rejected", "retired"), ("🔴", "red_bg")),
)
_DEFAULT_STYLE = ("📝", "gray_bg")
_HEADING_RE = re.compile(r"^#{2,3}\s+\S")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def doc_icon(doc):
    return doc.meta.get("icon") or DOC_ICON


def folder_icon(path, index):
    if index and index.meta.get("icon"):
        return index.meta["icon"]
    return SECTION_ICONS.get(posixpath.basename(path).lower(), FOLDER_ICON)


def callout(meta):
    """The front matter summary (status, owner, ...) as a coloured Notion callout."""
    parts = [f"**{label}:** {meta[key]}" for key, label in _META_LABELS if meta.get(key)]
    if not parts:
        return ""
    status = meta.get("status", "").strip().lower()
    icon, color = next((style for names, style in _STATUS_STYLES if status in names), _DEFAULT_STYLE)
    return f'<callout icon="{icon}" color="{color}">\n\t{" · ".join(parts)}\n</callout>'


def link(title, url):
    return "[%s](%s)" % (title.replace("[", "(").replace("]", ")"), url)


def breadcrumb(crumbs):
    """`crumbs` is a list of (title, url), root first."""
    return " / ".join(link(title, url) for title, url in crumbs)


def footer(previous, following, home_url=None):
    """`← Previous | Docs home | Next →`; `previous` and `following` are (title, url) or None."""
    parts = []
    if previous:
        parts.append("← " + link(*previous))
    if home_url:
        parts.append(link("Docs home", home_url))
    if following:
        parts.append(link(*following) + " →")
    return "---\n\n" + " | ".join(parts) if parts else ""


def wants_toc(body):
    """True when the body has enough `##`/`###` headings (outside code fences) for a contents block."""
    count, in_fence = 0, False
    for line in body.split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
        elif not in_fence and _HEADING_RE.match(line):
            count += 1
    return count >= _TOC_MIN_HEADINGS


def join_blocks(*blocks):
    return "\n\n".join(b.strip("\n") for b in blocks if b and b.strip()) + "\n"
