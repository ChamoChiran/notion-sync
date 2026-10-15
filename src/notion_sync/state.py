import json
from pathlib import Path


class PublishState:
    """Maps doc paths to Notion page ids (and content hashes) in a JSON file.

    Commit the file to the docs repo so every run updates the same pages.
    """

    def __init__(self, path):
        self._path = Path(path)
        self.database_id = None
        self.data_source_id = None
        self.pages = {}  # doc path -> {"id": ..., "hash": ...}
        if self._path.exists():
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self.database_id = data.get("database_id")
            self.data_source_id = data.get("data_source_id")
            self.pages = data.get("pages", {})

    def page_ids(self):
        return {path: entry["id"] for path, entry in self.pages.items()}

    def save(self):
        data = {
            "database_id": self.database_id,
            "data_source_id": self.data_source_id,
            "pages": dict(sorted(self.pages.items())),
        }
        self._path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
