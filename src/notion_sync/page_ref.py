import re
from dataclasses import dataclass

from .errors import PageRefError

_HEX = "[0-9a-fA-F]"
_PLAIN_ID_RE = re.compile(rf"(?<!{_HEX})({_HEX}{{32}})(?!{_HEX})")
_DASHED_ID_RE = re.compile(
    rf"(?<!{_HEX})({_HEX}{{8}}-{_HEX}{{4}}-{_HEX}{{4}}-{_HEX}{{4}}-{_HEX}{{12}})(?!{_HEX})"
)


@dataclass(frozen=True)
class PageRef:
    """Identifies a Notion page; built from a URL or a raw (dashed or plain) ID."""

    id: str

    @classmethod
    def parse(cls, text):
        # Notion URLs end with the ID, optionally after a title slug whose last
        # character may itself be a hex digit, so match on word boundaries.
        matches = _PLAIN_ID_RE.findall(text) or [
            m.replace("-", "") for m in _DASHED_ID_RE.findall(text)
        ]
        if not matches:
            raise PageRefError(f"cannot find a page ID in: {text}")
        return cls(matches[-1].lower())
