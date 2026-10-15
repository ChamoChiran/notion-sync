import json
from pathlib import Path

STATE_VERSION = 3


class PublishState:
    """Maps the published page tree to Notion page ids, in a JSON file.

    Commit the file to the docs repo so every run updates the same pages.
    A file from an older layout (no matching version) is ignored and rebuilt.
    """

    def __init__(self, path):
        self._path = Path(path)
        self.root_id = None
        self.folders = {}  # folder path -> page id
        self.pages = {}  # doc path -> {"id": ..., "hash": ...}
        if self._path.exists():
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if data.get("version") == STATE_VERSION:
                self.root_id = data.get("root_id")
                self.folders = data.get("folders", {})
                self.pages = data.get("pages", {})

    def page_ids(self):
        return {path: entry["id"] for path, entry in self.pages.items()}

    def save(self):
        data = {
            "version": STATE_VERSION,
            "root_id": self.root_id,
            "folders": dict(sorted(self.folders.items())),
            "pages": dict(sorted(self.pages.items())),
        }
        self._path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
