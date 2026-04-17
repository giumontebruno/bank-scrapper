from __future__ import annotations

from catalog.normalization import assess_merchant_candidate, find_merchant_hint
from parsers.promo_blocks import PromoBlock, embedded_html_promo_blocks
from scrapers.common import BaseBankScraper, DownloadedSource
from utils.text import normalize_text


class ContinentalScraper(BaseBankScraper):
    bank_name = "continental"

    def _promo_blocks_from_source(self, source: DownloadedSource) -> list[PromoBlock]:
        if source.text is not None:
            blocks = embedded_html_promo_blocks(source.text, source_url=source.url, source_type=source.source_type)
            blocks = self._split_category_lines(blocks)
            if blocks:
                return blocks
        return super()._promo_blocks_from_source(source)

    def _split_category_lines(self, blocks: list[PromoBlock]) -> list[PromoBlock]:
        refined: list[PromoBlock] = []
        for block in blocks:
            lines = [line.strip(" -•\t") for line in block.text.splitlines() if line.strip()]
            promo_lines = [
                line
                for line in lines
                if "%" in line and any(token in normalize_text(line) for token in _CATEGORY_LINE_HINTS)
            ]
            # El help center de Continental suele condensar un calendario entero en un solo fragmento RSC.
            # Separar por líneas con % + rubro mejora mucho la utilidad para queries por categoría.
            if len(promo_lines) >= 2:
                for line in promo_lines:
                    refined.append(
                        PromoBlock(
                            title=line,
                            text=line,
                            source_type=block.source_type,
                            source_url=block.source_url,
                        )
                    )
                continue
            refined.append(block)
        return refined

    def extract_merchant(self, text: str, title: str | None = None) -> str | None:
        hint_keys = list(self.bank_config.get("merchant_category_hints", {}).keys())
        hinted = find_merchant_hint(text, hint_keys)
        if hinted and normalize_text(hinted) not in _CATEGORY_LINE_HINTS:
            return hinted

        candidate = super().extract_merchant(text, title=title)
        assessment = assess_merchant_candidate(candidate)
        if assessment.is_valid:
            return assessment.cleaned_name
        # En Continental muchas piezas son calendarios por rubro; mejor dejar el merchant en null que inventarlo.
        return None


_CATEGORY_LINE_HINTS = {
    "farmacias",
    "supermercados",
    "combustible",
    "tiendas",
    "gastronomia",
    "peluquerias",
    "spa",
}
