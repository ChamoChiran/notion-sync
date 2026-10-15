class NotionSyncError(Exception):
    """Base class for all expected, user-facing errors."""


class ConfigError(NotionSyncError):
    """Missing or invalid configuration."""


class PageRefError(NotionSyncError):
    """A page URL or ID could not be understood."""


class NotionApiError(NotionSyncError):
    """The Notion API returned an error response."""

    def __init__(self, status, method, path, detail):
        super().__init__(f"Notion API {status} on {method} {path}: {detail}")
        self.status = status
