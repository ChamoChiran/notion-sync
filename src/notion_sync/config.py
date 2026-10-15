import os
from dataclasses import dataclass

from .errors import ConfigError

DEFAULT_NOTION_VERSION = "2022-06-28"


@dataclass(frozen=True)
class Config:
    token: str
    notion_version: str = DEFAULT_NOTION_VERSION

    @classmethod
    def from_env(cls, environ=None):
        env = os.environ if environ is None else environ
        token = env.get("NOTION_TOKEN", "").strip()
        if not token:
            raise ConfigError("NOTION_TOKEN environment variable is not set")
        return cls(token=token, notion_version=env.get("NOTION_VERSION", DEFAULT_NOTION_VERSION))
