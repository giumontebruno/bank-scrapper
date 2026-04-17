from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from db.schema import metadata


def normalize_database_url(url: str) -> str:
    normalized = url.strip()
    if normalized.startswith("postgres://"):
        normalized = "postgresql+psycopg://" + normalized[len("postgres://") :]
    elif normalized.startswith("postgresql://"):
        normalized = "postgresql+psycopg://" + normalized[len("postgresql://") :]
    elif "://" not in normalized:
        normalized = f"sqlite:///{normalized}"
    return normalized


@dataclass
class Database:
    url: str
    engine: Engine

    @property
    def backend(self) -> str:
        return self.engine.dialect.name

    def initialize(self) -> None:
        metadata.create_all(self.engine)


def create_database(url: str) -> Database:
    normalized = normalize_database_url(url)
    connect_args = {"check_same_thread": False} if normalized.startswith("sqlite") else {}
    engine = create_engine(normalized, future=True, pool_pre_ping=True, connect_args=connect_args)
    database = Database(url=normalized, engine=engine)
    database.initialize()
    return database
