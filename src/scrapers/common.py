from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from catalog.data import infer_category_from_text
from catalog.normalization import assess_merchant_candidate, find_merchant_hint, resolve_merchant
from core.config import load_bank_sources
from core.logging import get_logger
from models.promotion import Promotion
from parsers.promo_blocks import PromoBlock, html_promo_blocks, text_promo_blocks
from utils.http import build_session
from utils.promo_extractors import (
    extract_cap_amount,
    extract_card_scope,
    extract_cashback_percent,
    extract_channel,
    extract_date_range,
    extract_discount_percent,
    extract_installments,
    extract_minimum_purchase,
    extract_payment_method,
    extract_valid_days,
)
from utils.text import normalize_text


@dataclass
class DownloadedSource:
    url: str
    source_type: str
    content_type: str
    text: str | None = None
    bytes_content: bytes | None = None


@dataclass
class ScraperRunMetrics:
    discovery_candidates_count: int = 0
    parsed_blocks_count: int = 0
    filtered_blocks_count: int = 0
    persisted_promotions_count: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "discovery_candidates_count": self.discovery_candidates_count,
            "parsed_blocks_count": self.parsed_blocks_count,
            "filtered_blocks_count": self.filtered_blocks_count,
            "persisted_promotions_count": self.persisted_promotions_count,
        }


class BaseBankScraper:
    bank_name: str = ""

    def __init__(self, session: requests.Session | None = None, config: dict[str, Any] | None = None) -> None:
        self.session = session or build_session()
        self.logger = get_logger(self.__class__.__name__)
        all_config = config or load_bank_sources()
        self.bank_config: dict[str, Any] = all_config.get(self.bank_name.lower(), {})
        self.timeout = self.bank_config.get("timeout", 20)

    def collect(self, month_ref: str) -> list[Promotion]:
        promotions, _ = self.collect_with_metrics(month_ref)
        return promotions

    def collect_with_metrics(self, month_ref: str) -> tuple[list[Promotion], ScraperRunMetrics]:
        sources = self.discover_sources(month_ref=month_ref)
        promotions: list[Promotion] = []
        metrics = ScraperRunMetrics(discovery_candidates_count=len(sources))
        for source in sources:
            try:
                blocks = self._promo_blocks_from_source(source)
            except Exception as exc:
                self.logger.warning("parse_source_failed", extra={"extra_data": {"url": source.url, "error": str(exc)}})
                continue
            metrics.parsed_blocks_count += len(blocks)
            for block in blocks:
                promotion = self.parse_block(block, month_ref=month_ref)
                if promotion and self._matches_month(promotion, month_ref):
                    promotions.append(promotion)
                else:
                    metrics.filtered_blocks_count += 1
        metrics.persisted_promotions_count = len(promotions)
        return promotions, metrics

    def discover_sources(self, month_ref: str | None = None) -> list[DownloadedSource]:
        discovered: dict[tuple[str, str], DownloadedSource] = {}
        seeds = self.bank_config.get("sources", [])
        allowed_domains = set(self.bank_config.get("allowed_domains", []))
        for seed in seeds:
            url = seed["url"]
            source_type = seed["source_type"]
            follow_links = seed.get("follow_links", True)
            try:
                fetched = self.fetch_source(url, source_type=source_type)
            except Exception as exc:
                self.logger.warning("fetch_seed_failed", extra={"extra_data": {"url": url, "error": str(exc)}})
                continue
            if fetched is None:
                continue
            discovered[(fetched.url, fetched.source_type)] = fetched
            if follow_links and fetched.text and source_type in {"html_listing", "html_detail", "html_benefits"}:
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

    def fetch_source(self, url: str, source_type: str) -> DownloadedSource | None:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if source_type == "sitemap" and ("xml" in content_type or url.lower().endswith(".xml")):
            return DownloadedSource(
                url=response.url,
                source_type=source_type,
                content_type=content_type or "text/xml",
                text=response.text,
            )
        if "html" in content_type:
            return DownloadedSource(url=response.url, source_type=source_type, content_type=content_type, text=response.text)
        if "pdf" in content_type or url.lower().endswith(".pdf"):
            return DownloadedSource(
                url=response.url,
                source_type=source_type,
                content_type=content_type or "application/pdf",
                bytes_content=response.content,
            )
        self.logger.warning("unsupported_content_type", extra={"extra_data": {"url": url, "content_type": content_type}})
        return None

    def parse_block(self, block: PromoBlock, month_ref: str) -> Promotion | None:
        text = block.text
        if not _looks_like_promo(text):
            return None
        if _looks_like_pdf_binary_dump(text):
            return None
        if _looks_like_operational_block(text):
            return None
        merchant_candidate = self.extract_merchant(text, title=block.title)
        if merchant_candidate and ("comercios adheridos" in normalize_text(merchant_candidate) or len(normalize_text(merchant_candidate)) > 80):
            merchant_candidate = None
        resolution = resolve_merchant(merchant_candidate)
        start_date, end_date = extract_date_range(text, fallback_year=int(month_ref.split("-")[0]))

        discount = extract_discount_percent(text)
        cashback = extract_cashback_percent(text)
        installments = extract_installments(text)
        payment_method = extract_payment_method(text)
        channel = extract_channel(text)
        card_scope = extract_card_scope(text)
        valid_days = extract_valid_days(text)
        cap_amount = extract_cap_amount(text)
        minimum_purchase_amount = extract_minimum_purchase(text)
        category = self.infer_category(" ".join(part for part in [resolution.merchant_normalized, merchant_candidate, text] if part))
        confidence = self._confidence_score(text, merchant_candidate, discount, cashback, start_date, end_date)
        # Esta salida conserva promos de categoría aunque no logremos un merchant limpio.
        # Sirve para bancos que publican campañas genéricas de "supermercados" o "combustibles".
        if resolution.brand_normalized is None and category is None:
            return None

        return Promotion(
            bank=self.bank_name.title(),
            title=block.title or (resolution.merchant_normalized or "Promocion"),
            category=category,
            merchant=merchant_candidate,
            merchant_raw=merchant_candidate,
            merchant_normalized=resolution.merchant_normalized,
            brand_normalized=resolution.brand_normalized,
            merchant_aliases=resolution.aliases,
            discount_percent=discount,
            cashback_percent=cashback,
            installments=installments,
            benefit_type=self._benefit_type(discount, cashback, installments),
            promo_mechanic=self._benefit_type(discount, cashback, installments),
            payment_method=payment_method,
            channel=channel,
            card_scope=card_scope,
            start_date=start_date,
            end_date=end_date,
            valid_days=valid_days,
            cap_amount=cap_amount,
            minimum_purchase_amount=minimum_purchase_amount,
            month_ref=month_ref,
            source_type=block.source_type,
            source_url=block.source_url,
            source_document=Path(urlparse(block.source_url).path).name or None,
            summary=_summary(text),
            raw_text=text,
            confidence_score=confidence,
        )

    def infer_category(self, merchant_or_text: str | None) -> str | None:
        if not merchant_or_text:
            return None
        generic_category = infer_category_from_text(merchant_or_text)
        normalized = normalize_text(merchant_or_text)
        mapping = self.bank_config.get("merchant_category_hints", {})
        if generic_category is not None and generic_category not in {"retail", "otros"}:
            return generic_category
        for key, category in mapping.items():
            if normalize_text(key) in normalized:
                return category
        return generic_category

    def extract_merchant(self, text: str, title: str | None = None) -> str | None:
        candidates = [title] if title else []
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        candidates.extend(lines[:8])
        hint_keys = list(self.bank_config.get("merchant_category_hints", {}).keys())
        for candidate in candidates:
            if not candidate:
                continue
            hinted = find_merchant_hint(candidate, hint_keys)
            if hinted:
                return hinted
        for candidate in candidates:
            if not candidate:
                continue
            assessment = assess_merchant_candidate(candidate)
            if assessment.is_valid:
                return assessment.cleaned_name
        hinted = find_merchant_hint(text, hint_keys)
        if hinted:
            return hinted
        return None

    def _promo_blocks_from_source(self, source: DownloadedSource) -> list[PromoBlock]:
        if source.text is not None:
            return html_promo_blocks(source.text, source_url=source.url, source_type=source.source_type)
        if source.bytes_content is not None:
            text = extract_pdf_text(source.bytes_content)
            return text_promo_blocks(text, source_url=source.url, source_type=source.source_type)
        return []

    def _discover_links(self, html: str, base_url: str, allowed_domains: set[str]) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        links: list[str] = []
        excluded_url_hints = [normalize_text(item) for item in self.bank_config.get("exclude_url_hints", [])]
        excluded_text_hints = [normalize_text(item) for item in self.bank_config.get("exclude_link_text_hints", [])]
        for anchor in soup.find_all("a", href=True):
            href = urljoin(base_url, anchor["href"])
            parsed = urlparse(href)
            if allowed_domains and parsed.netloc not in allowed_domains:
                continue
            normalized = href.lower()
            anchor_text = normalize_text(anchor.get_text(" ", strip=True))
            if any(token in normalize_text(normalized) for token in excluded_url_hints):
                continue
            if any(token in anchor_text for token in excluded_text_hints):
                continue
            if normalized.endswith(".pdf") or any(token in normalized for token in self.bank_config.get("detail_hints", [])):
                links.append(href)
        return list(dict.fromkeys(links))

    def _matches_month(self, promotion: Promotion, month_ref: str) -> bool:
        year, month = [int(part) for part in month_ref.split("-")]
        month_start = date(year, month, 1)
        month_end = date(year, month, 28)
        if month == 12:
            month_end = date(year, 12, 31)
        elif month in {1, 3, 5, 7, 8, 10}:
            month_end = date(year, month, 31)
        elif month != 2:
            month_end = date(year, month, 30)
        if promotion.start_date and promotion.end_date:
            return not (promotion.end_date < month_start or promotion.start_date > month_end)
        return promotion.month_ref == month_ref or promotion.end_date is None

    def _benefit_type(self, discount: float | None, cashback: float | None, installments: int | None) -> str | None:
        if cashback is not None:
            return "cashback"
        if discount is not None:
            return "discount"
        if installments is not None:
            return "installments"
        return None

    def _confidence_score(
        self,
        text: str,
        merchant: str | None,
        discount: float | None,
        cashback: float | None,
        start_date: date | None,
        end_date: date | None,
    ) -> float:
        score = 0.2
        if merchant:
            score += 0.2
        if discount is not None or cashback is not None:
            score += 0.2
        if start_date or end_date:
            score += 0.2
        if len(text) > 120:
            score += 0.1
        return min(score, 0.95)


def extract_pdf_text(payload: bytes) -> str:
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(payload)) as pdf:
            return "\n\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception:
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(payload))
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            # Fallback defensivo: evita romper la corrida si el parser PDF nativo queda bloqueado por el entorno.
            # En producción conviene preferir `pdfplumber`; este decode simple solo preserva algo de evidencia cruda.
            return payload.decode("latin-1", errors="ignore")


def _summary(text: str) -> str | None:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:200] if compact else None


def _infer_source_type(url: str) -> str:
    lowered = url.lower()
    if lowered.endswith(".pdf"):
        if any(token in lowered for token in ["interior", "zonal", "zona", "ciudad-del-este", "encarnacion"]):
            return "pdf_zonal"
        return "pdf_campaign"
    return "html_detail"


def _looks_like_promo(text: str) -> bool:
    lowered = text.lower()
    normalized = normalize_text(text)
    indicators = [
        "descuento",
        "reintegro",
        "cashback",
        "cuotas",
        "vigencia",
        "tope",
        "en caja",
        "compra minima",
        "compra minima",
    ]
    return "%" in lowered or any(token in normalized for token in indicators)


def _looks_like_pdf_binary_dump(text: str) -> bool:
    normalized = text.lower()
    markers = ["%pdf", " obj", "endobj", "/mediabox", "/contents", "xref"]
    return sum(marker in normalized for marker in markers) >= 2


def _looks_like_operational_block(text: str) -> bool:
    normalized = normalize_text(text)
    operational_hints = [
        "comunicaciones",
        "canales oficiales",
        "se recomienda al cliente",
        "notificaciones en la aplicacion movil del banco",
        "pagina web https www ueno com py",
        "anexo i",
        "nombre del comercio adherido",
        "plazo de acreditacion del reintegro",
    ]
    return any(token in normalized for token in operational_hints)
