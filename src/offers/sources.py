from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from core.config import PROJECT_ROOT


SUPPORTED_SUPPLEMENTAL_SOURCE_TYPES = {"manual_source", "merchant_campaign", "social_signal"}
DEFAULT_SUPPLEMENTAL_OFFERS_PATH = PROJECT_ROOT / "config" / "manual_offers.yaml"


def load_supplemental_offer_sources(path: str | Path | None = None) -> list[dict[str, Any]]:
    config_path = Path(path) if path else DEFAULT_SUPPLEMENTAL_OFFERS_PATH
    if not config_path.exists():
        return []

    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    items = payload if isinstance(payload, list) else payload.get("offers", [])
    if not isinstance(items, list):
        return []

    sources: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        source_type = str(item.get("source_type") or "").strip()
        if source_type not in SUPPORTED_SUPPLEMENTAL_SOURCE_TYPES:
            continue
        sources.append(item)
    return sources
