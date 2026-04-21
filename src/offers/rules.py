from __future__ import annotations

from datetime import date

from offers.models import Offer


ACTIONABLE_TYPES = {"bank_promo"}
VISIBLE_QUALITY = {"high", "medium", "low"}


def is_today_relevant(offer: Offer, *, today: date | None = None) -> bool:
    if today is None:
        return True
    if offer.valid_from and offer.valid_from > today:
        return False
    if offer.valid_until and offer.valid_until < today:
        return False
    return True


def is_home_eligible(offer: Offer) -> bool:
    if not offer.is_today_relevant:
        return False
    if offer.offer_quality_label == "fallback":
        return False
    if offer.promo_type not in VISIBLE_QUALITY and offer.promo_type == "catalog_fallback":
        return False
    if offer.is_generic and offer.is_category_only and not _has_clear_benefit(offer):
        return False
    return True


def is_featured_candidate(offer: Offer) -> bool:
    if not is_home_eligible(offer):
        return False
    if offer.offer_quality_label not in {"high", "medium"}:
        return False
    if offer.promo_type not in ACTIONABLE_TYPES:
        return False
    return bool(offer.merchant_normalized and _has_clear_benefit(offer))


def offer_sort_score(offer: Offer) -> float:
    benefit_strength = max(
        offer.discount_percent or 0,
        offer.cashback_percent or 0,
        min((offer.installments or 0) * 2, 30),
    )
    quality_weight = {"high": 100, "medium": 70, "low": 30, "fallback": 0}.get(offer.offer_quality_label, 0)
    promo_weight = {"bank_promo": 40, "generic_benefit": 10, "voucher": 5, "loyalty_reward": 3}.get(offer.promo_type, 0)
    merchant_weight = 25 if offer.merchant_normalized else 0
    featured_weight = 20 if offer.is_featured_candidate else 0
    generic_penalty = -25 if offer.is_generic else 0
    return quality_weight + promo_weight + merchant_weight + featured_weight + benefit_strength + generic_penalty


def _has_clear_benefit(offer: Offer) -> bool:
    return any(
        value is not None
        for value in [offer.discount_percent, offer.cashback_percent, offer.installments, offer.cap_amount]
    )
