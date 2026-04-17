from __future__ import annotations

from catalog.service import CatalogService
from catalog.normalization import resolve_merchant
from models.promotion import FuelPrice, Promotion, QueryMatch
from query.ranking import (
    PROMO_TYPE_PRIORITY,
    QUALITY_LABEL_ORDER,
    benefit_label,
    build_base_price_explanation,
    build_explanation,
    estimate_final_price,
    infer_promo_type,
    ranking_score,
    result_quality,
)
from query.repository import PromotionRepository
from utils.text import normalize_text


class QueryEngine:
    def __init__(self, repository: PromotionRepository, catalog: CatalogService | None = None) -> None:
        self.repository = repository
        self.catalog = catalog or CatalogService()

    def query(self, text: str) -> dict[str, object]:
        category = self.catalog.infer_category(text)
        normalized_text = normalize_text(text)
        promotions = self.repository.list_promotions()
        fuel_prices = self.repository.list_fuel_prices()
        octane = self._detect_octane(normalized_text)
        broad_query = self._is_broad_query(normalized_text, category)

        matches: list[QueryMatch] = []
        used_fuel_keys: set[tuple[str, int]] = set()

        for promotion in promotions:
            effective_category = self._promotion_category(promotion)
            if category and effective_category and effective_category != category:
                if category != "combustible":
                    continue

            candidate_name = promotion.brand_normalized or promotion.merchant_normalized or promotion.merchant
            if category and effective_category is None and category != "combustible":
                continue

            if category == "combustible" and octane is not None and not candidate_name and effective_category == "combustible":
                generic_prices = [item for item in fuel_prices if item.octane == octane]
                if generic_prices:
                    for fuel_price in generic_prices:
                        used_fuel_keys.add((fuel_price.brand, fuel_price.octane))
                        matches.append(
                            self._build_match(
                                promotion,
                                fuel_price=fuel_price,
                                merchant_override=fuel_price.brand,
                                category_override=effective_category,
                            )
                        )
                    continue

            fuel_price = None
            if category == "combustible" and octane is not None and candidate_name:
                fuel_price = self._match_fuel_price(fuel_prices, octane=octane, candidate_name=candidate_name)
                if fuel_price is not None:
                    used_fuel_keys.add((fuel_price.brand, fuel_price.octane))

            matches.append(self._build_match(promotion, fuel_price=fuel_price, category_override=effective_category))

        if category == "combustible" and octane is not None:
            for fuel_price in fuel_prices:
                if fuel_price.octane != octane:
                    continue
                if (fuel_price.brand, fuel_price.octane) in used_fuel_keys:
                    continue
                matches.append(self._build_fuel_only_match(fuel_price))

        if not matches and category and category != "combustible":
            fallback_merchants = self.catalog.merchants_for_category(category) or self._fallback_merchants_for_category(promotions, category)
            for merchant in fallback_merchants[:5]:
                matches.append(self._build_catalog_fallback_match(merchant=merchant, category=category))

        matches = self._sort_matches(matches, broad_query=broad_query)
        if broad_query:
            matches = self._prune_for_broad_query(matches)
        return {"query": text, "matches": [match.dict() for match in matches]}

    def _build_match(
        self,
        promotion: Promotion,
        fuel_price: FuelPrice | None = None,
        merchant_override: str | None = None,
        category_override: str | None = None,
    ) -> QueryMatch:
        promo_type = infer_promo_type(promotion)
        quality_score, quality_label = result_quality(promotion, fuel_price, promo_type=promo_type)
        final_price = estimate_final_price(promotion, fuel_price.base_price if fuel_price else None)
        return QueryMatch(
            merchant=merchant_override
            or promotion.merchant_normalized
            or promotion.brand_normalized
            or promotion.merchant
            or (category_override or promotion.category or "Desconocido"),
            category=category_override or promotion.category,
            bank=promotion.bank,
            benefit=benefit_label(promotion),
            promo_type=promo_type,
            ranking_score=ranking_score(
                promotion,
                fuel_price.base_price if fuel_price else None,
                promo_type=promo_type,
                quality_score=quality_score,
            ),
            result_quality_score=quality_score,
            result_quality_label=quality_label,
            price_base=fuel_price.base_price if fuel_price else None,
            price_final_estimated=final_price,
            valid_until=promotion.end_date.isoformat() if promotion.end_date else None,
            source_url=promotion.source_url,
            explanation=build_explanation(promotion, fuel_price, promo_type),
        )

    def _build_fuel_only_match(self, fuel_price: FuelPrice) -> QueryMatch:
        promo_type = infer_promo_type(None, fuel_price_only=True)
        quality_score, quality_label = result_quality(None, fuel_price, promo_type=promo_type)
        return QueryMatch(
            merchant=fuel_price.brand,
            category="combustible",
            bank=None,
            benefit="sin promoción detectada",
            promo_type=promo_type,
            ranking_score=ranking_score(None, fuel_price.base_price, promo_type=promo_type, quality_score=quality_score),
            result_quality_score=quality_score,
            result_quality_label=quality_label,
            price_base=fuel_price.base_price,
            price_final_estimated=fuel_price.base_price,
            valid_until=None,
            source_url=fuel_price.source_url,
            explanation=build_base_price_explanation(fuel_price),
        )

    def _build_catalog_fallback_match(self, merchant: str, category: str) -> QueryMatch:
        synthetic = Promotion(
            bank="Catalog",
            title=merchant,
            category=category,
            merchant=merchant,
            merchant_raw=merchant,
            merchant_normalized=merchant,
            source_type="catalog_fallback",
            source_url="catalog://fallback",
            raw_text=merchant,
            confidence_score=0.0,
        )
        promo_type = infer_promo_type(synthetic, is_catalog_fallback=True)
        quality_score, quality_label = result_quality(
            synthetic,
            None,
            promo_type=promo_type,
            is_catalog_fallback=True,
        )
        return QueryMatch(
            merchant=merchant,
            category=category,
            bank=None,
            benefit="sin promoción detectada",
            promo_type=promo_type,
            ranking_score=ranking_score(
                synthetic,
                None,
                promo_type=promo_type,
                quality_score=quality_score,
                is_catalog_fallback=True,
            ),
            result_quality_score=quality_score,
            result_quality_label=quality_label,
            price_base=None,
            price_final_estimated=None,
            valid_until=None,
            source_url=None,
            explanation=f"Comercio relacionado por catálogo para {category}, sin promoción activa detectada hoy.",
        )

    def _sort_matches(self, matches: list[QueryMatch], *, broad_query: bool) -> list[QueryMatch]:
        return sorted(
            matches,
            key=lambda item: (
                -QUALITY_LABEL_ORDER.get(item.result_quality_label or "fallback", 0),
                item.price_final_estimated is None if not broad_query else False,
                item.price_final_estimated or 999999999,
                -PROMO_TYPE_PRIORITY.get(item.promo_type or "catalog_fallback", 0),
                -(item.ranking_score or -999999),
            ),
        )

    def _prune_for_broad_query(self, matches: list[QueryMatch]) -> list[QueryMatch]:
        strong = [item for item in matches if item.result_quality_label in {"high", "medium"}]
        low = [item for item in matches if item.result_quality_label == "low"]
        fallback = [item for item in matches if item.result_quality_label == "fallback"]
        if strong:
            # En consultas amplias preferimos calidad, pero dejamos una cola corta de resultados
            # debiles para no esconder promos genericas o fallback utiles cuando no hay mucho mas.
            return strong[:8] + low[:4] + fallback[:2]
        if low:
            return low[:8] + fallback[:2]
        return fallback[:5]

    @staticmethod
    def _is_broad_query(text: str, category: str | None) -> bool:
        broad_phrases = [
            "que banco me conviene hoy",
            "quiero promociones",
            "quiero ver beneficios",
            "beneficios",
            "promociones",
        ]
        return category is None or any(phrase in text for phrase in broad_phrases)

    @staticmethod
    def _detect_octane(text: str) -> int | None:
        if "97" in text:
            return 97
        if "95" in text:
            return 95
        return None

    def _promotion_category(self, promotion: Promotion) -> str | None:
        if promotion.category:
            return promotion.category
        payload = " ".join(
            part for part in [promotion.title, promotion.merchant, promotion.merchant_normalized, promotion.summary, promotion.raw_text] if part
        )
        return self.catalog.infer_category(payload)

    def _fallback_merchants_for_category(self, promotions: list[Promotion], category: str) -> list[str]:
        candidates: list[str] = []
        for promotion in promotions:
            if self._promotion_category(promotion) != category:
                continue
            merchant = promotion.brand_normalized or promotion.merchant_normalized or promotion.merchant
            if merchant and merchant not in candidates:
                candidates.append(merchant)
        return candidates

    def _match_fuel_price(self, fuel_prices: list[FuelPrice], octane: int, candidate_name: str):
        candidate_resolution = resolve_merchant(candidate_name)
        candidate_brand = candidate_resolution.brand_normalized or candidate_resolution.merchant_normalized
        for item in fuel_prices:
            if item.octane != octane:
                continue
            item_brand = resolve_merchant(item.brand).brand_normalized or resolve_merchant(item.brand).merchant_normalized
            if candidate_brand and item_brand and candidate_brand == item_brand:
                return item
            if self.catalog.merchant_matches(item.brand, candidate_name):
                return item
        return None
