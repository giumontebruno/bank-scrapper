from __future__ import annotations

from catalog.normalization import assess_merchant_candidate, find_merchant_hint
from scrapers.common import BaseBankScraper


class SudamerisScraper(BaseBankScraper):
    bank_name = "sudameris"

    def extract_merchant(self, text: str, title: str | None = None) -> str | None:
        candidates = [title] if title else []
        candidates.extend(line.strip() for line in text.splitlines() if line.strip())
        for candidate in candidates[:6]:
            assessment = assess_merchant_candidate(candidate)
            if assessment.is_valid:
                return assessment.cleaned_name

        hint_keys = list(self.bank_config.get("merchant_category_hints", {}).keys())
        hinted = find_merchant_hint(text, hint_keys)
        if hinted:
            assessment = assess_merchant_candidate(hinted)
            return hinted if assessment.is_valid else None

        # Sudameris mezcla placeholders de listado con detalle real. Preferimos merchant nulo
        # antes que persistir un rubro corto como si fuera comercio especifico.
        candidate = super().extract_merchant(text, title=title)
        assessment = assess_merchant_candidate(candidate)
        return assessment.cleaned_name if assessment.is_valid else None
