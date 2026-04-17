from __future__ import annotations

from catalog.data import CATEGORY_TO_MERCHANTS, MERCHANT_ALIASES, infer_category_from_text
from catalog.normalization import merchant_equivalent, resolve_merchant
from utils.text import normalize_text


class CatalogService:
    def infer_category(self, query_text: str) -> str | None:
        return infer_category_from_text(query_text)

    def merchants_for_category(self, category: str | None) -> list[str]:
        if not category:
            return []
        return CATEGORY_TO_MERCHANTS.get(category, [])

    def merchant_matches(self, merchant_name: str, candidate: str) -> bool:
        if merchant_equivalent(merchant_name, candidate):
            return True
        merchant_norm = normalize_text(merchant_name)
        candidate_norm = normalize_text(candidate)
        if candidate_norm and candidate_norm in merchant_norm:
            return True
        aliases = MERCHANT_ALIASES.get(candidate, [])
        normalized_aliases = {normalize_text(alias) for alias in aliases}
        if merchant_norm in normalized_aliases or any(alias and alias in merchant_norm for alias in normalized_aliases):
            return True
        left_brand = resolve_merchant(merchant_name).brand_normalized
        right_brand = resolve_merchant(candidate).brand_normalized
        return bool(left_brand and right_brand and left_brand == right_brand)
