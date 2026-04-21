from __future__ import annotations

from collections import Counter

from offers.models import Offer
from offers.rules import is_home_eligible, offer_sort_score


CATEGORY_LABELS = {
    "supermercados": "Supermercados",
    "combustible": "Combustible",
    "gastronomia": "GastronomÃ­a",
    "retail": "Retail",
    "indumentaria": "Indumentaria",
    "tecnologia": "TecnologÃ­a",
    "hogar": "Hogar",
    "salud": "Farmacia / salud",
    "viajes": "Viajes",
    "entretenimiento": "Entretenimiento",
    "ferreteria": "FerreterÃ­a",
    "otros": "Otros",
}


def build_today_feed(offers: list[Offer], *, per_category: int = 4) -> dict[str, object]:
    eligible = [offer for offer in offers if is_home_eligible(offer)]
    eligible.sort(key=offer_sort_score, reverse=True)
    counts = Counter(offer.category or "otros" for offer in eligible)
    grouped: dict[str, list[Offer]] = {}
    for offer in eligible:
        category = offer.category or "otros"
        grouped.setdefault(category, [])
        if len(grouped[category]) < per_category:
            grouped[category].append(offer)
    categories = [
        {"key": key, "label": CATEGORY_LABELS.get(key, key.title()), "count": counts[key]}
        for key in grouped
    ]
    featured = [offer for offer in eligible if offer.is_featured_candidate][:6]
    if not featured:
        featured = eligible[:6]
    return {
        "categories": categories,
        "grouped": grouped,
        "featured_offers": featured,
        "today_offers_by_category": grouped,
        "fuel_offers_today": grouped.get("combustible", []),
        "top_bank_offers": featured,
        "top_discount_offers": [offer for offer in eligible if offer.discount_percent is not None][:6],
        "top_cashback_offers": [offer for offer in eligible if offer.cashback_percent is not None][:6],
        "top_installment_offers": [offer for offer in eligible if offer.installments is not None][:6],
        "total": len(eligible),
    }
