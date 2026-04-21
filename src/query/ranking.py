from __future__ import annotations

from models.promotion import FuelPrice, Promotion
from utils.text import normalize_text

PROMO_TYPE_PRIORITY = {
    "bank_promo": 4,
    "generic_benefit": 2,
    "voucher": 1,
    "loyalty_reward": 1,
    "catalog_fallback": 0,
}

QUALITY_LABEL_ORDER = {
    "high": 3,
    "medium": 2,
    "low": 1,
    "fallback": 0,
}


def estimate_final_price(promotion: Promotion, base_price: float | None) -> float | None:
    if base_price is None:
        return None
    if promotion.minimum_purchase_amount is not None and base_price < promotion.minimum_purchase_amount:
        return round(base_price, 2)

    percent = 0.0
    if promotion.discount_percent is not None:
        percent = max(percent, promotion.discount_percent)
    if promotion.cashback_percent is not None:
        percent = max(percent, promotion.cashback_percent)
    effective = base_price * (1 - (percent / 100))

    # Esta heuristica asume una compra unitaria para no sobreestimar el ahorro cuando el tope es bajo.
    if promotion.cap_amount is not None:
        savings = min(base_price - effective, promotion.cap_amount)
        effective = base_price - savings
    return round(effective, 2)


def infer_promo_type(
    promotion: Promotion | None,
    *,
    is_catalog_fallback: bool = False,
    fuel_price_only: bool = False,
) -> str:
    if is_catalog_fallback:
        return "catalog_fallback"
    if promotion is None:
        return "generic_benefit" if fuel_price_only else "catalog_fallback"

    normalized = normalize_text(" ".join(part for part in [promotion.title, promotion.raw_text, promotion.payment_method] if part))
    if any(token in normalized for token in ["solo puntos", "puntos", "canjear", "premio", "reward"]):
        if any(token in normalized for token in ["vale", "voucher"]):
            return "voucher"
        return "loyalty_reward"
    if is_generic_promotion(promotion):
        return "generic_benefit"
    return "bank_promo"


def result_quality(
    promotion: Promotion | None,
    fuel_price: FuelPrice | None,
    *,
    promo_type: str,
    is_catalog_fallback: bool = False,
) -> tuple[float, str]:
    if is_catalog_fallback:
        return 0.05, "fallback"

    score = 0.0
    if promotion is None and fuel_price is not None:
        score += 0.35
    if promotion is not None:
        if _has_clear_merchant(promotion):
            score += 0.22
        elif promotion.category:
            score += 0.08
        if _has_clear_benefit(promotion):
            score += 0.2
        if promotion.end_date:
            score += 0.08
        if promotion.cap_amount is not None or promotion.minimum_purchase_amount is not None:
            score += 0.05
        if promotion.channel:
            score += 0.05
        if promotion.category:
            score += 0.05
        if promotion.confidence_score:
            score += min(promotion.confidence_score, 1.0) * 0.15
        if is_generic_promotion(promotion):
            score -= 0.18
    if fuel_price is not None:
        score += 0.2
        if promotion is not None and estimate_final_price(promotion, fuel_price.base_price) is not None:
            score += 0.15

    if promo_type == "bank_promo":
        score += 0.15
    elif promo_type == "generic_benefit":
        score -= 0.05
    elif promo_type == "voucher":
        score -= 0.18
    elif promo_type == "loyalty_reward":
        score -= 0.24

    score = max(0.0, min(round(score, 4), 1.0))
    if score >= 0.75:
        return score, "high"
    if score >= 0.45:
        return score, "medium"
    if score >= 0.2:
        return score, "low"
    return score, "fallback"


def ranking_score(
    promotion: Promotion | None,
    base_price: float | None,
    *,
    promo_type: str,
    quality_score: float,
    is_catalog_fallback: bool = False,
) -> float:
    if is_catalog_fallback:
        return round(-1.5 + quality_score, 4)

    score = quality_score * 4
    if promotion is None:
        score += 0.5 if base_price is not None else 0.0
        score -= (base_price or 0) / 1000
        return round(score, 4)

    final_price = estimate_final_price(promotion, base_price)
    if base_price is not None and final_price is not None:
        score += (base_price - final_price) / 5
        score -= final_price / 10000
    if promotion.installments is not None:
        score += min(promotion.installments, 12) * 0.04
    if promotion.valid_days:
        score += 0.06
    if promotion.minimum_purchase_amount:
        score -= promotion.minimum_purchase_amount / 1000000
    if promotion.cap_amount:
        score += min(promotion.cap_amount / 100000, 0.4)
    if promo_type == "bank_promo":
        score += 0.25
    elif promo_type == "generic_benefit":
        score -= 0.12
    elif promo_type == "voucher":
        score -= 0.35
    elif promo_type == "loyalty_reward":
        score -= 0.45
    return round(score, 4)


def benefit_label(promotion: Promotion) -> str:
    pieces: list[str] = []
    if promotion.discount_percent is not None:
        pieces.append(f"{promotion.discount_percent:.0f}% desc.")
    if promotion.cashback_percent is not None:
        pieces.append(f"{promotion.cashback_percent:.0f}% reintegro")
    if promotion.installments is not None:
        pieces.append(f"{promotion.installments} cuotas")
    if promotion.cap_amount is not None:
        pieces.append(f"tope {promotion.cap_amount:.0f} Gs.")
    return " + ".join(pieces) if pieces else (promotion.benefit_type or "beneficio no especificado")


def build_explanation(promotion: Promotion, fuel_price: FuelPrice | None, promo_type: str) -> str:
    benefit = benefit_label(promotion)
    if promo_type == "catalog_fallback":
        return f"Comercio relacionado por catalogo para {promotion.category or 'la necesidad consultada'}, sin promocion activa detectada hoy."
    if fuel_price:
        final_price = estimate_final_price(promotion, fuel_price.base_price)
        return (
            f"Base {fuel_price.brand} {fuel_price.octane}: {fuel_price.base_price:.0f} Gs. "
            f"Beneficio {benefit}. Final estimado: {final_price:.2f} Gs."
        )
    return f"Promo detectada para {promotion.merchant_normalized or promotion.merchant or promotion.category or 'resultado generico'} con {benefit}."


def build_base_price_explanation(fuel_price: FuelPrice) -> str:
    return f"Precio base sin promocion detectada para {fuel_price.brand} {fuel_price.octane}: {fuel_price.base_price:.0f} Gs."


def is_generic_promotion(promotion: Promotion) -> bool:
    if _has_clear_merchant(promotion):
        return False
    if not promotion.brand_normalized and not promotion.merchant_normalized:
        return True
    normalized = normalize_text(" ".join(part for part in [promotion.title, promotion.merchant, promotion.summary, promotion.raw_text[:160]] if part))
    normalized_title = normalize_text(promotion.title or "")
    if not normalized_title or normalized_title in {"lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"}:
        return True
    generic_markers = [
        "beneficio no especificado",
        "conocer promos",
        "conoce mas",
        "miercoles hasta",
        "jueves hasta",
        "viernes hasta",
        "fin de semana hasta",
        "todos los dias",
        "exclusivo pos",
        "promociones",
        "beneficios",
    ]
    return any(marker in normalized for marker in generic_markers)


def _has_clear_merchant(promotion: Promotion) -> bool:
    candidate = promotion.brand_normalized or promotion.merchant_normalized or promotion.merchant
    if not candidate:
        return False
    normalized = normalize_text(candidate)
    if len(normalized) < 3:
        return False
    generic_terms = {
        "...",
        "combustible",
        "supermercados",
        "supermercado",
        "gastronomia",
        "tiendas",
        "salud",
        "ferreteria",
        "miercoles de",
        "jueves",
        "viernes de",
        "exclusivo pos",
        "conocer promos",
        "conoce mas",
        "promociones",
        "beneficios",
        "cuotas",
        "hoteles",
        "bicicleterias",
        "fin de semana",
        "i m",
        "n caja",
    }
    noisy_fragments = [
        "ser socio",
        "tiene sus beneficios",
        "rubros favoritos",
        "medios de pago",
    ]
    return normalized not in generic_terms and "hasta" not in normalized and "promo" not in normalized and not any(
        fragment in normalized for fragment in noisy_fragments
    )


def _has_clear_benefit(promotion: Promotion) -> bool:
    return any(
        value is not None
        for value in [
            promotion.discount_percent,
            promotion.cashback_percent,
            promotion.installments,
            promotion.cap_amount,
        ]
    )
