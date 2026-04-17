from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import requests
from bs4 import BeautifulSoup

from core.logging import get_logger
from models.promotion import FuelPrice
from utils.http import build_session
from utils.text import normalize_text

FUEL_SOURCE_URL = "https://www.combustibles.com.py/"
ALLOWED_OCTANES = {95, 97}
SECTION_TO_OCTANE = {
    "nafta comun": None,
    "nafta común": None,
    "nafta intermedia": 95,
    "nafta premium": 97,
}
BRAND_ALIASES = {
    "shell": "Shell",
    "copetrol": "Copetrol",
    "petropar": "Petropar",
    "petrobras": "Petrobras",
    "enex": "Enex",
    "petrosur": "Petrobras",
}


class FuelPriceCollector:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or build_session()
        self.logger = get_logger(__name__)

    def collect(self) -> list[FuelPrice]:
        response = self.session.get(FUEL_SOURCE_URL, timeout=20)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type:
            self.logger.warning("content_type_not_html", extra={"extra_data": {"content_type": content_type}})
            return []
        return parse_fuel_prices_from_html(response.text, FUEL_SOURCE_URL)


def parse_fuel_prices_from_html(html: str, source_url: str) -> list[FuelPrice]:
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")
    timestamp = datetime.now(timezone.utc).isoformat()
    prices = parse_fuel_prices_from_text(soup.get_text("\n", strip=True), source_url=source_url, captured_at=timestamp)
    if prices:
        return prices

    text_blocks = [block.get_text(" ", strip=True) for block in soup.find_all(["tr", "article", "div", "li"])]
    fallback_prices: list[FuelPrice] = []

    for block in text_blocks:
        normalized = normalize_text(block)
        brand = _extract_brand(normalized)
        octane = _extract_octane(normalized)
        price = _extract_price(block)
        if brand is None or octane is None or price is None:
            continue
        fallback_prices.append(
            FuelPrice(
                brand=brand,
                octane=octane,
                base_price=price,
                captured_at=timestamp,
                source_url=source_url,
                raw_text=block,
            )
        )

    unique: dict[tuple[str, int], FuelPrice] = {}
    for item in fallback_prices:
        unique[(item.brand, item.octane)] = item
    return list(unique.values())


def parse_fuel_prices_from_text(text: str, source_url: str, captured_at: str | None = None) -> list[FuelPrice]:
    normalized_lines = [_clean_line(line) for line in text.splitlines()]
    lines = [line for line in normalized_lines if line]
    captured_at = captured_at or datetime.now(timezone.utc).isoformat()
    prices: list[FuelPrice] = []
    current_octane: int | None = None

    # El sitio actual publica una secuencia lineal de encabezado -> marca -> precio.
    # Regla de negocio actual: "Nafta Intermedia" se expone como 95 y "Nafta Premium" como 97.
    # Preferimos leer esa estructura explícita antes que depender de selectores HTML frágiles.
    for index, line in enumerate(lines):
        normalized = normalize_text(line)
        if normalized in SECTION_TO_OCTANE:
            current_octane = SECTION_TO_OCTANE[normalized]
            continue
        if current_octane not in ALLOWED_OCTANES:
            continue

        brand = _extract_brand(normalized)
        if brand is None:
            continue

        price = None
        evidence_parts = [line]
        for look_ahead in lines[index + 1 : index + 4]:
            evidence_parts.append(look_ahead)
            price = _extract_price(look_ahead)
            if price is not None:
                break
        if price is None:
            continue

        prices.append(
            FuelPrice(
                brand=brand,
                octane=current_octane,
                base_price=price,
                captured_at=captured_at,
                source_url=source_url,
                raw_text=" | ".join(evidence_parts),
            )
        )

    unique: dict[tuple[str, int], FuelPrice] = {}
    for item in prices:
        unique[(item.brand, item.octane)] = item
    return list(unique.values())


def _extract_brand(text: str) -> str | None:
    for alias, canonical in BRAND_ALIASES.items():
        if alias in text:
            return canonical
    return None


def _extract_octane(text: str) -> int | None:
    for label, octane in SECTION_TO_OCTANE.items():
        if label in text:
            return octane
    for octane in ALLOWED_OCTANES:
        if f" {octane} " in f" {text} ":
            return octane
    return None


def _extract_price(text: str) -> float | None:
    candidates = []
    for token in text.replace("Gs.", " ").replace("Gs", " ").split():
        cleaned = token.replace(".", "").replace(",", ".").strip()
        if cleaned.count(".") > 1:
            continue
        try:
            value = Decimal(cleaned)
        except InvalidOperation:
            continue
        if value >= 1000:
            candidates.append(float(value))
    return candidates[0] if candidates else None


def _clean_line(value: str) -> str:
    return value.replace("\xa0", " ").strip()
