from __future__ import annotations

from collections import OrderedDict
from datetime import date
from typing import Any

from models.promotion import Promotion
from offers.models import Offer
from offers.rules import is_featured_candidate, is_today_relevant, offer_sort_score
from query.ranking import benefit_label, infer_promo_type, is_generic_promotion, result_quality
from utils.text import normalize_text


def build_offer_catalog(
    promotions: list[Promotion],
    *,
    supplemental_sources: list[dict[str, Any]] | None = None,
    today: date | None = None,
) -> list[Offer]:
    offers = [_promotion_to_offer(item, today=today) for item in promotions]
    offers.extend(_source_to_offer(item, today=today) for item in supplemental_sources or [])
    return _dedupe_offers(offers)


def _promotion_to_offer(promotion: Promotion, *, today: date | None) -> Offer:
    promo_type = infer_promo_type(promotion)
    quality_score, quality_label = result_quality(promotion, None, promo_type=promo_type)
    channels = [item.strip() for item in [promotion.channel, promotion.payment_method] if item and item.strip()]
    benefit = _benefit_type(promotion)
    offer = Offer(
        bank=promotion.bank,
        merchant_raw=promotion.merchant_raw or promotion.merchant,
        merchant_normalized=promotion.merchant_normalized or promotion.brand_normalized or promotion.merchant,
        merchant_group=promotion.brand_normalized,
        category=promotion.category or "otros",
        subcategory=None,
        benefit_type=benefit,
        benefit_summary=benefit_label(promotion),
        discount_percent=promotion.discount_percent,
        cashback_percent=promotion.cashback_percent,
        installments=promotion.installments,
        cap_amount=promotion.cap_amount,
        min_purchase_amount=promotion.minimum_purchase_amount,
        valid_from=promotion.start_date,
        valid_until=promotion.end_date,
        valid_days=promotion.valid_days,
        channels=channels,
        source_url=promotion.source_url,
        source_type=_canonical_source_type(promotion.source_type),
        source_document=promotion.source_document,
        source_family="bank",
        confidence_score=promotion.confidence_score or 0.0,
        offer_quality_score=quality_score,
        offer_quality_label=quality_label,
        promo_type=promo_type,
        is_generic=is_generic_promotion(promotion),
        is_category_only=not bool(promotion.merchant_normalized or promotion.brand_normalized),
        is_today_relevant=_dates_are_today_relevant(promotion.start_date, promotion.end_date, today=today),
        source_promotion_titles=[promotion.title],
    )
    offer.is_featured_candidate = is_featured_candidate(offer)
    return offer


def _source_to_offer(payload: dict[str, Any], *, today: date | None) -> Offer:
    source_type = str(payload.get("source_type") or "manual_source")
    discount = _optional_float(payload.get("discount_percent"))
    cashback = _optional_float(payload.get("cashback_percent"))
    installments = _optional_int(payload.get("installments"))
    valid_from = _optional_date(payload.get("valid_from") or payload.get("start_date"))
    valid_until = _optional_date(payload.get("valid_until") or payload.get("end_date"))
    merchant = _optional_text(payload.get("merchant_normalized") or payload.get("merchant"))
    category = _optional_text(payload.get("category")) or "otros"
    benefit_type = _benefit_type_from_values(discount, cashback, installments, _optional_text(payload.get("benefit_type")))
    benefit_summary = _optional_text(payload.get("benefit_summary")) or _source_benefit_summary(
        discount=discount,
        cashback=cashback,
        installments=installments,
        fallback=_optional_text(payload.get("summary") or payload.get("title")),
    )
    confidence = _optional_float(payload.get("confidence_score"))
    if confidence is None:
        confidence = 0.35 if source_type == "social_signal" else 0.65
    quality_score, quality_label = _source_quality(
        merchant=merchant,
        category=category,
        discount=discount,
        cashback=cashback,
        installments=installments,
        confidence=confidence,
        source_type=source_type,
    )
    offer = Offer(
        bank=_optional_text(payload.get("bank")),
        merchant_raw=_optional_text(payload.get("merchant_raw") or payload.get("merchant")),
        merchant_normalized=merchant,
        merchant_group=_optional_text(payload.get("merchant_group") or payload.get("brand_normalized")),
        category=category,
        subcategory=_optional_text(payload.get("subcategory")),
        benefit_type=benefit_type,
        benefit_summary=benefit_summary,
        discount_percent=discount,
        cashback_percent=cashback,
        installments=installments,
        cap_amount=_optional_float(payload.get("cap_amount")),
        min_purchase_amount=_optional_float(payload.get("min_purchase_amount") or payload.get("minimum_purchase_amount")),
        valid_from=valid_from,
        valid_until=valid_until,
        valid_days=_optional_list(payload.get("valid_days")),
        channels=_optional_list(payload.get("channels")),
        source_url=_optional_text(payload.get("source_url")),
        source_type=source_type,
        source_document=_optional_text(payload.get("source_document")),
        source_family=_source_family(source_type),
        external_source_id=_optional_text(payload.get("external_source_id") or payload.get("id")),
        confidence_score=confidence,
        offer_quality_score=quality_score,
        offer_quality_label=quality_label,
        promo_type=_source_promo_type(source_type, merchant, benefit_type),
        is_generic=not bool(merchant) or benefit_type == "unknown",
        is_category_only=not bool(merchant),
        is_today_relevant=_dates_are_today_relevant(valid_from, valid_until, today=today),
        source_promotion_titles=[_optional_text(payload.get("title")) or benefit_summary],
    )
    offer.is_featured_candidate = is_featured_candidate(offer)
    return offer


def _dedupe_offers(offers: list[Offer]) -> list[Offer]:
    buckets: OrderedDict[str, Offer] = OrderedDict()
    for offer in sorted(offers, key=offer_sort_score, reverse=True):
        key = _offer_key(offer)
        existing = buckets.get(key)
        if existing is None:
            buckets[key] = offer
            continue
        existing.source_count += offer.source_count
        existing.source_promotion_titles.extend(title for title in offer.source_promotion_titles if title not in existing.source_promotion_titles)
        if offer_sort_score(offer) > offer_sort_score(existing):
            offer.source_count = existing.source_count
            offer.source_promotion_titles = existing.source_promotion_titles
            buckets[key] = offer
    return sorted(buckets.values(), key=offer_sort_score, reverse=True)


def _offer_key(offer: Offer) -> str:
    parts = [
        normalize_text(offer.bank or ""),
        normalize_text(offer.merchant_group or offer.merchant_normalized or ""),
        normalize_text(offer.category or ""),
        str(offer.discount_percent or ""),
        str(offer.cashback_percent or ""),
        str(offer.installments or ""),
        normalize_text(offer.benefit_type or ""),
        str(offer.valid_until or ""),
    ]
    return "|".join(parts)


def _benefit_type(promotion: Promotion) -> str:
    has_discount = promotion.discount_percent is not None
    has_cashback = promotion.cashback_percent is not None
    has_installments = promotion.installments is not None
    if sum([has_discount, has_cashback, has_installments]) > 1:
        return "mixed"
    if has_discount:
        return "discount"
    if has_cashback:
        return "cashback"
    if has_installments:
        return "installments"
    return promotion.benefit_type or "unknown"


def _benefit_type_from_values(
    discount: float | None,
    cashback: float | None,
    installments: int | None,
    fallback: str | None,
) -> str:
    has_discount = discount is not None
    has_cashback = cashback is not None
    has_installments = installments is not None
    if sum([has_discount, has_cashback, has_installments]) > 1:
        return "mixed"
    if has_discount:
        return "discount"
    if has_cashback:
        return "cashback"
    if has_installments:
        return "installments"
    return fallback or "unknown"


def _source_benefit_summary(
    *,
    discount: float | None,
    cashback: float | None,
    installments: int | None,
    fallback: str | None,
) -> str:
    pieces: list[str] = []
    if discount is not None:
        pieces.append(f"{discount:g}% descuento")
    if cashback is not None:
        pieces.append(f"{cashback:g}% reintegro")
    if installments is not None:
        pieces.append(f"{installments} cuotas")
    if pieces:
        return " + ".join(pieces)
    return fallback or "Beneficio a verificar"


def _source_quality(
    *,
    merchant: str | None,
    category: str,
    discount: float | None,
    cashback: float | None,
    installments: int | None,
    confidence: float,
    source_type: str,
) -> tuple[float, str]:
    # Fuentes complementarias pueden ser utiles, pero no deben saltar por encima
    # de promos bancarias verificadas si llegan como senales sociales debiles.
    score = confidence * 60
    if merchant:
        score += 20
    if category and category != "otros":
        score += 10
    if any(value is not None for value in [discount, cashback, installments]):
        score += 20
    if source_type == "social_signal":
        score -= 15
    label = "high" if score >= 85 else "medium" if score >= 55 else "low"
    return round(score, 2), label


def _source_promo_type(source_type: str, merchant: str | None, benefit_type: str | None) -> str:
    if source_type == "social_signal":
        return "generic_benefit" if not merchant else "bank_promo"
    if source_type in {"manual_source", "merchant_campaign"} and merchant and benefit_type != "unknown":
        return "bank_promo"
    return "generic_benefit"


def _source_family(source_type: str) -> str:
    if source_type == "merchant_campaign":
        return "merchant"
    if source_type == "social_signal":
        return "social"
    return "manual"


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _optional_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _canonical_source_type(source_type: str | None) -> str | None:
    mapping = {
        "html_listing": "bank_html",
        "html_detail": "bank_detail_page",
        "pdf_campaign": "bank_pdf",
        "pdf_zonal": "bank_pdf",
    }
    return mapping.get(source_type or "", source_type)


def _dates_are_today_relevant(valid_from: date | None, valid_until: date | None, *, today: date | None) -> bool:
    if today is None:
        return True
    if valid_from and valid_from > today:
        return False
    if valid_until and valid_until < today:
        return False
    return True
