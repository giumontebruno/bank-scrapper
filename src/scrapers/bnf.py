from __future__ import annotations

from datetime import date

from catalog.normalization import resolve_merchant
from models.promotion import Promotion
from parsers.promo_blocks import PromoBlock
from scrapers.common import BaseBankScraper, DownloadedSource, _infer_source_type
from utils.promo_extractors import extract_date_range
from utils.text import normalize_text


class BNFScraper(BaseBankScraper):
    bank_name = "bnf"

    def discover_sources(self, month_ref: str | None = None) -> list[DownloadedSource]:
        discovered: dict[tuple[str, str], DownloadedSource] = {}
        seeds = self.bank_config.get("sources", [])
        allowed_domains = set(self.bank_config.get("allowed_domains", []))
        for seed in seeds:
            url = seed["url"]
            source_type = seed["source_type"]
            try:
                fetched = self.fetch_source(url, source_type=source_type)
            except Exception as exc:
                self.logger.warning("fetch_seed_failed", extra={"extra_data": {"url": url, "error": str(exc)}})
                continue
            if fetched is None:
                continue
            discovered[(fetched.url, fetched.source_type)] = fetched
            if fetched.text and source_type == "html_listing":
                for link in self._discover_links(fetched.text, base_url=url, allowed_domains=allowed_domains):
                    child_type = _infer_source_type(link)
                    try:
                        child = self.fetch_source(link, source_type=child_type)
                    except Exception as exc:
                        self.logger.warning("fetch_child_failed", extra={"extra_data": {"url": link, "error": str(exc)}})
                        continue
                    if child is not None:
                        discovered[(child.url, child.source_type)] = child
        return list(discovered.values())

    def _promo_blocks_from_source(self, source: DownloadedSource):
        if source.source_type == "html_listing":
            return []
        return super()._promo_blocks_from_source(source)

    def parse_block(self, block: PromoBlock, month_ref: str) -> Promotion | None:
        promotion = super().parse_block(block, month_ref)
        if promotion is not None:
            promotion.bank = "BNF"
            return promotion
        return self._parse_reward_voucher(block, month_ref)

    def _parse_reward_voucher(self, block: PromoBlock, month_ref: str) -> Promotion | None:
        normalized = normalize_text(block.text)
        if "puntos" not in normalized and "vale" not in normalized:
            return None

        merchant = self._extract_voucher_merchant(block.text, block.title)
        category = self.infer_category(" ".join(part for part in [merchant, block.title, block.text] if part))
        if merchant is None and category is None:
            return None

        resolution = resolve_merchant(merchant)
        _, end_date = extract_date_range(block.text, fallback_year=int(month_ref.split("-")[0]))
        if end_date is None:
            end_date = self._extract_inline_expiry(block.text)

        title = resolution.merchant_normalized or (
            block.title if block.title and normalize_text(block.title) not in {"o puntos", "solo puntos"} else None
        ) or "Voucher BNF"
        return Promotion(
            bank="BNF",
            title=title,
            category=category,
            merchant=merchant,
            merchant_raw=merchant,
            merchant_normalized=resolution.merchant_normalized,
            brand_normalized=resolution.brand_normalized,
            merchant_aliases=resolution.aliases,
            benefit_type="voucher",
            promo_mechanic="voucher",
            payment_method="puntos",
            channel="app",
            end_date=end_date,
            month_ref=month_ref,
            source_type=block.source_type,
            source_url=block.source_url,
            source_document=block.source_url.rstrip("/").split("/")[-1] or None,
            summary=title,
            raw_text=block.text,
            confidence_score=0.45,
        )

    def _extract_voucher_merchant(self, text: str, title: str | None) -> str | None:
        candidates = [title, text]
        hint_keys = self.bank_config.get("merchant_category_hints", {}).keys()
        for candidate in candidates:
            if not candidate:
                continue
            normalized = normalize_text(candidate)
            for hint in hint_keys:
                if normalize_text(hint) in normalized:
                    return hint
        return None

    def _extract_inline_expiry(self, text: str) -> date | None:
        import re

        match = re.search(r"antes del\s+(\d{1,2})/(\d{1,2})/(\d{4})", text.lower())
        if match:
            day_value, month_value, year_value = match.groups()
            return date(int(year_value), int(month_value), int(day_value))
        return None
