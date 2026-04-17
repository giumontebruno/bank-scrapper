from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    app_env: str = "local"
    database_url: str = ""
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    log_level: str = "INFO"
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    enable_admin_endpoints: bool = True
    bank_sources_path: Path = PROJECT_ROOT / "config" / "bank_sources.yaml"

    @property
    def is_production_like(self) -> bool:
        return self.app_env.lower() in {"production", "prod", "staging", "online"}


def load_bank_sources(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else get_settings().bank_sources_path
    with config_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env = _load_env_file(PROJECT_ROOT / ".env")
    app_env = (os.getenv("APP_ENV") or env.get("APP_ENV") or "local").strip().lower()
    database_url = (os.getenv("DATABASE_URL") or env.get("DATABASE_URL") or "").strip()
    if not database_url:
        if app_env in {"production", "prod", "staging", "online"}:
            raise ConfigError("DATABASE_URL es obligatorio cuando APP_ENV es production/staging/online.")
        database_url = f"sqlite:///{(PROJECT_ROOT / 'data' / 'processed' / 'catalog.sqlite').as_posix()}"

    host = (os.getenv("API_HOST") or env.get("API_HOST") or "127.0.0.1").strip()
    port_raw = (os.getenv("API_PORT") or env.get("API_PORT") or "8000").strip()
    log_level = (os.getenv("LOG_LEVEL") or env.get("LOG_LEVEL") or "INFO").strip().upper()
    origins_raw = (os.getenv("API_CORS_ORIGINS") or env.get("API_CORS_ORIGINS") or "*").strip()
    enable_admin_raw = os.getenv("ENABLE_ADMIN_ENDPOINTS") or env.get("ENABLE_ADMIN_ENDPOINTS")
    bank_sources_raw = os.getenv("BANK_SOURCES_PATH") or env.get("BANK_SOURCES_PATH")

    return Settings(
        app_env=app_env,
        database_url=database_url,
        api_host=host,
        api_port=int(port_raw),
        log_level=log_level,
        cors_origins=_parse_csv(origins_raw),
        enable_admin_endpoints=_parse_bool(enable_admin_raw, default=app_env in {"local", "development", "dev"}),
        bank_sources_path=Path(bank_sources_raw) if bank_sources_raw else PROJECT_ROOT / "config" / "bank_sources.yaml",
    )


def reset_settings_cache() -> None:
    get_settings.cache_clear()


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_csv(value: str) -> list[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or ["*"]
