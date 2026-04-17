from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from typing import Any

from models.promotion import Promotion
from query.ranking import benefit_label, infer_promo_type, result_quality


@dataclass
class SearchFilters:
    bank: str = ""
    category: str = ""
    quality: str = ""
    promo_type: str = ""


EXAMPLE_QUERIES = [
    "quiero comprar en super",
    "que tarjeta me conviene para 95",
    "que tarjeta me conviene para 97",
    "quiero ver promos de ropa",
    "quiero salir a comer",
    "quiero comprar en farmacia",
    "necesito clavos",
]

QUALITY_LABELS = ["high", "medium", "low", "fallback"]
PROMO_TYPES = ["bank_promo", "generic_benefit", "voucher", "loyalty_reward", "catalog_fallback"]
MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def apply_match_filters(matches: list[dict[str, Any]], filters: SearchFilters) -> list[dict[str, Any]]:
    items = matches
    if filters.bank:
        items = [item for item in items if (item.get("bank") or "").lower() == filters.bank.lower()]
    if filters.category:
        items = [item for item in items if (item.get("category") or "").lower() == filters.category.lower()]
    if filters.quality:
        items = [item for item in items if (item.get("result_quality_label") or "").lower() == filters.quality.lower()]
    if filters.promo_type:
        items = [item for item in items if (item.get("promo_type") or "").lower() == filters.promo_type.lower()]
    return items


def summarize_match_kind(item: dict[str, Any]) -> str:
    promo_type = item.get("promo_type") or "catalog_fallback"
    if promo_type == "bank_promo":
        if item.get("merchant") and item.get("category"):
            return "Promo específica"
        return "Promo bancaria"
    if promo_type == "generic_benefit":
        return "Promo genérica"
    if promo_type in {"voucher", "loyalty_reward"}:
        return "Voucher / canje"
    return "Fallback de catálogo"


def fuel_recommendations(matches_95: list[dict[str, Any]], matches_97: list[dict[str, Any]]) -> dict[int, dict[str, Any] | None]:
    return {
        95: matches_95[0] if matches_95 else None,
        97: matches_97[0] if matches_97 else None,
    }


def normalize_recent_queries(raw_cookie: str | None) -> list[str]:
    if not raw_cookie:
        return []
    try:
        payload = json.loads(raw_cookie)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    items = [item.strip() for item in payload if isinstance(item, str) and item.strip()]
    deduped: list[str] = []
    for item in items:
        if item not in deduped:
            deduped.append(item)
    return deduped[:5]


def update_recent_queries(existing: list[str], query: str) -> list[str]:
    query = query.strip()
    if not query:
        return existing[:5]
    items = [query] + [item for item in existing if item != query]
    return items[:5]


def build_empty_state(query: str, raw_matches: list[dict[str, Any]], filtered_matches: list[dict[str, Any]]) -> dict[str, str] | None:
    if not query:
        return None
    if filtered_matches:
        return None
    if raw_matches and all(item.get("promo_type") == "catalog_fallback" for item in raw_matches):
        return {
            "title": "Solo hubo coincidencia por rubro, sin promo real hoy",
            "message": "Encontramos relación por categoría o merchant de catálogo, pero no una promoción activa y específica para esta búsqueda.",
        }
    if raw_matches:
        return {
            "title": "Tus filtros dejaron la búsqueda sin resultados visibles",
            "message": "Probá quitar banco, calidad o tipo para volver a ver resultados útiles.",
        }
    return {
        "title": "Sin resultados útiles para esa búsqueda",
        "message": "Probá otra necesidad o una de las consultas rápidas sugeridas.",
    }


def promotion_card(item: Promotion) -> dict[str, Any]:
    promo_type = infer_promo_type(item)
    quality_score, quality_label = result_quality(item, None, promo_type=promo_type)
    return {
        "bank": item.bank,
        "title": item.title,
        "merchant": item.merchant_normalized or item.brand_normalized or item.merchant or item.title,
        "merchant_state": "Por merchant" if (item.merchant_normalized or item.brand_normalized) else "Por rubro",
        "category": item.category or "otros",
        "benefit": benefit_label(item),
        "promo_type": promo_type,
        "quality_label": quality_label,
        "quality_score": quality_score,
        "valid_until": item.end_date.isoformat() if item.end_date else None,
        "source_type": item.source_type,
        "source_url": item.source_url,
        "payment_method": item.payment_method,
        "channel": item.channel,
        "summary": item.summary or item.title,
        "confidence_score": item.confidence_score,
    }


def apply_promotion_filters(
    items: list[dict[str, Any]],
    *,
    bank: str = "",
    category: str = "",
    promo_type: str = "",
    quality: str = "",
) -> list[dict[str, Any]]:
    filtered = items
    if bank:
        filtered = [item for item in filtered if item["bank"].lower() == bank.lower()]
    if category:
        filtered = [item for item in filtered if item["category"].lower() == category.lower()]
    if promo_type:
        filtered = [item for item in filtered if item["promo_type"].lower() == promo_type.lower()]
    if quality:
        filtered = [item for item in filtered if item["quality_label"].lower() == quality.lower()]
    return filtered


def paginate(items: list[Any], *, page: int, page_size: int) -> tuple[list[Any], int]:
    total_pages = max(1, ((len(items) - 1) // page_size) + 1) if items else 1
    current_page = max(1, min(page, total_pages))
    start = (current_page - 1) * page_size
    return items[start : start + page_size], total_pages


def validate_month(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if not MONTH_PATTERN.match(value):
        raise ValueError("Mes inválido. Usá formato YYYY-MM, por ejemplo 2026-04.")
    return value


def validate_bank(value: str | None, allowed: set[str]) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if value.lower() not in {item.lower() for item in allowed}:
        raise ValueError(f"Banco inválido: {value}.")
    return value


def now_month_ref() -> str:
    return datetime.now().strftime("%Y-%m")


def timed_call(fn: Any, *args: Any, **kwargs: Any) -> tuple[Any, float]:
    start = perf_counter()
    result = fn(*args, **kwargs)
    return result, round(perf_counter() - start, 2)
