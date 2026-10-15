"""Page furniture around a document's body: breadcrumb, summary line, footer."""
import re

TOC_BLOCK = "<table_of_contents/>"
_TOC_MIN_HEADINGS = 3

_META_LABELS = (
    ("status", "Status"),
    ("owner", "Owner"),
    ("component", "Component"),
    ("last_reviewed", "Last reviewed"),
)
_HEADING_RE = re.compile(r"^#{2,3}\s+\S")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def summary(meta):
    """The front matter (status, owner, ...) as a one-line quote, since pages have no properties."""
    parts = [f"**{label}:** {meta[key]}" for key, label in _META_LABELS if meta.get(key)]
    return "> " + " · ".join(parts) if parts else ""


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
