import json


class NotionSyncError(Exception):
    """Base class for all expected, user-facing errors."""


class ConfigError(NotionSyncError):
    """Missing or invalid configuration."""


class PageRefError(NotionSyncError):
    """A page URL or ID could not be understood."""


class NotionApiError(NotionSyncError):
    """The Notion API returned an error response."""

    def __init__(self, status, method, path, body):
        self.status = status
        self.code = None
        message = body
        try:
            parsed = json.loads(body)
            self.code = parsed.get("code")
            message = parsed.get("message", body)
        except (ValueError, AttributeError):
            pass
        code = f" ({self.code})" if self.code else ""
        super().__init__(f"Notion API {status}{code} on {method} {path}: {message}")
