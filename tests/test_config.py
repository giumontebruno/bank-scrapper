from __future__ import annotations

from pathlib import Path

import pytest

from core.config import ConfigError, get_settings, reset_settings_cache
from db.connection import normalize_database_url


def test_settings_use_local_defaults_when_env_missing(monkeypatch) -> None:
    for key in [
        "APP_ENV",
        "DATABASE_URL",
        "API_HOST",
        "API_PORT",
        "LOG_LEVEL",
        "API_CORS_ORIGINS",
        "ENABLE_ADMIN_ENDPOINTS",
        "ADMIN_TOKEN",
    ]:
        monkeypatch.delenv(key, raising=False)
    reset_settings_cache()

    settings = get_settings()

    assert settings.app_env == "local"
    assert settings.database_url.startswith("sqlite:///")
    assert settings.api_host == "127.0.0.1"
    assert settings.api_port == 8000
    assert settings.admin_token == ""


def test_settings_reads_admin_token(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'catalog.sqlite').as_posix()}")
    monkeypatch.setenv("ADMIN_TOKEN", "secret-token")
    reset_settings_cache()

    settings = get_settings()

    assert settings.admin_token == "secret-token"


def test_settings_require_database_url_in_production(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("BANK_SOURCES_PATH", str(tmp_path / "bank_sources.yaml"))
    reset_settings_cache()

    with pytest.raises(ConfigError):
        get_settings()


def test_normalize_database_url_supports_postgres_and_sqlite_paths() -> None:
    assert normalize_database_url("postgres://user:pass@localhost/db") == "postgresql+psycopg://user:pass@localhost/db"
    assert normalize_database_url("postgresql://user:pass@localhost/db") == "postgresql+psycopg://user:pass@localhost/db"
    assert normalize_database_url("data/processed/catalog.sqlite").startswith("sqlite:///")
