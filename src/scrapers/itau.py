from __future__ import annotations

from catalog.normalization import assess_merchant_candidate, find_merchant_hint
from scrapers.common import BaseBankScraper
from utils.promo_extractors import is_disclaimerish_text


class ItauScraper(BaseBankScraper):
    bank_name = "itau"

    def extract_merchant(self, text: str, title: str | None = None) -> str | None:
        hint_keys = list(self.bank_config.get("merchant_category_hints", {}).keys())
        hinted = find_merchant_hint(text, hint_keys)
        if hinted:
            return hinted

        candidate = super().extract_merchant(text, title=title)
        if candidate and is_disclaimerish_text(candidate):
            return None

        assessment = assess_merchant_candidate(candidate)
        return assessment.cleaned_name if assessment.is_valid else None
