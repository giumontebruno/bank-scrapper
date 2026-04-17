from __future__ import annotations

from models.promotion import Promotion
from utils.text import normalize_text

SOURCE_PRIORITY = {
    "html_detail": 4,
    "pdf_campaign": 3,
    "pdf_zonal": 3,
    "html_listing": 2,
}


def dedupe_promotions(promotions: list[Promotion]) -> list[Promotion]:
    unique: dict[tuple[str, ...], Promotion] = {}
    for promotion in promotions:
        key = _promotion_key(promotion)
        current = unique.get(key)
        if current is None or _score(promotion) > _score(current):
            unique[key] = promotion
    return list(unique.values())


def _promotion_key(promotion: Promotion) -> tuple[str, ...]:
    return (
        normalize_text(promotion.bank),
        normalize_text(promotion.merchant_normalized or promotion.brand_normalized or promotion.merchant or ""),
        normalize_text(promotion.category or ""),
        str(promotion.discount_percent or ""),
        str(promotion.cashback_percent or ""),
        str(promotion.installments or ""),
        str(promotion.start_date or ""),
        str(promotion.end_date or ""),
        str(promotion.cap_amount or ""),
        str(promotion.minimum_purchase_amount or ""),
        normalize_text(",".join(promotion.valid_days or [])),
        normalize_text(promotion.card_scope or ""),
        normalize_text(promotion.channel or ""),
    )


def _score(promotion: Promotion) -> float:
    score = promotion.confidence_score
    score += SOURCE_PRIORITY.get(promotion.source_type, 0)
    if promotion.summary:
        score += 0.1
    if promotion.raw_text:
        score += min(len(promotion.raw_text) / 1000, 0.5)
    return score
