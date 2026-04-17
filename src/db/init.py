from __future__ import annotations

from core.config import get_settings
from db.connection import Database, create_database


def init_database(url: str | None = None) -> Database:
    return create_database(url or get_settings().database_url)
