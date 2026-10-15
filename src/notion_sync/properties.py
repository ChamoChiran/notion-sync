import re

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Folder prefix -> default document type, first match wins.
_TYPE_BY_PATH = (
    ("architecture/decisions/", "ADR"),
    ("architecture/components/", "Component"),
    ("architecture/flows/", "Flow"),
    ("architecture/", "Architecture"),
    ("runbooks/", "Runbook"),
    ("policies/", "Policy"),
    ("onboarding/", "Onboarding"),
    ("templates/", "Template"),
)


class DocsDatabaseSchema:
    """Property schema of the Notion database that holds the docs."""

    @staticmethod
    def properties():
        return {
            "Name": {"type": "title", "title": {}},
            "Type": {"type": "select", "select": {}},
            "Component": {"type": "select", "select": {}},
            "Status": {"type": "select", "select": {}},
            "Owner": {"type": "rich_text", "rich_text": {}},
            "Last reviewed": {"type": "date", "date": {}},
            "Source": {"type": "url", "url": {}},
            "Path": {"type": "rich_text", "rich_text": {}},
        }


class PagePropertyBuilder:
    """Builds Notion page properties from a Document's front matter and path."""

    def __init__(self, source_base_url=None):
        self._source_base = source_base_url.rstrip("/") + "/" if source_base_url else None

    def build(self, doc):
        meta = doc.meta
        props = {
            "Name": {"title": [{"text": {"content": doc.title[:2000]}}]},
            "Type": {"select": {"name": self._type(doc)}},
            "Path": self._text(doc.path),
        }
        for key, prop in (("component", "Component"), ("status", "Status")):
            if meta.get(key):
                props[prop] = {"select": {"name": meta[key].replace(",", " ")}}
        if meta.get("owner"):
            props["Owner"] = self._text(meta["owner"])
        if _DATE_RE.match(meta.get("last_reviewed", "")):
            props["Last reviewed"] = {"date": {"start": meta["last_reviewed"]}}
        if self._source_base:
            props["Source"] = {"url": self._source_base + doc.path}
        return props

    @staticmethod
    def _type(doc):
        if doc.meta.get("type"):
            return doc.meta["type"].replace(",", " ")
        for prefix, kind in _TYPE_BY_PATH:
            if doc.path.startswith(prefix):
                return kind
        return "Guide"

    @staticmethod
    def _text(value):
        return {"rich_text": [{"text": {"content": value[:2000]}}]}
