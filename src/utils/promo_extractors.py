from __future__ import annotations

import re
from datetime import date

MONTHS = {
    "ene": 1,
    "enero": 1,
    "feb": 2,
    "febrero": 2,
    "mar": 3,
    "marzo": 3,
    "abr": 4,
    "abril": 4,
    "may": 5,
    "mayo": 5,
    "jun": 6,
    "junio": 6,
    "jul": 7,
    "julio": 7,
    "ago": 8,
    "agosto": 8,
    "sep": 9,
    "sept": 9,
    "septiembre": 9,
    "oct": 10,
    "octubre": 10,
    "nov": 11,
    "noviembre": 11,
    "dic": 12,
    "diciembre": 12,
}

DAY_ALIASES = {
    "lunes": "monday",
    "martes": "tuesday",
    "miercoles": "wednesday",
    "miércoles": "wednesday",
    "jueves": "thursday",
    "viernes": "friday",
    "sabado": "saturday",
    "sábado": "saturday",
    "domingo": "sunday",
}

DISCLAIMER_MARKERS = (
    "no aplica",
    "bases y condiciones",
    "ver bases",
    "comercios adheridos",
    "locales seleccionados",
    "usuarios a los que les parecio util",
    "te fue util",
    "enviar comentario",
    "descarga la app",
)


def split_promo_blocks(text: str) -> list[str]:
    blocks = [chunk.strip() for chunk in re.split(r"\n\s*\n", text) if chunk.strip()]
    return blocks or [text]


def is_disclaimerish_text(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in DISCLAIMER_MARKERS)


def extract_date_range(text: str, fallback_year: int | None = None) -> tuple[date | None, date | None]:
    normalized = text.lower()
    first = re.search(r"del\s+(\d{1,2})\s+al\s+(\d{1,2})\s+de\s+([a-záéíóú]+)(?:\s+de\s+(\d{4}))?", normalized)
    if first:
        day_start, day_end, month_name, year_value = first.groups()
        month = MONTHS.get(_strip_accents(month_name))
        year = int(year_value) if year_value else (fallback_year or date.today().year)
        if month:
            return date(year, month, int(day_start)), date(year, month, int(day_end))

    second = re.search(
        r"vigencia[:\s]+(\d{1,2})/(\d{1,2})/(\d{4})\s*(?:al|-|a)\s*(\d{1,2})/(\d{1,2})/(\d{4})",
        normalized,
    )
    if second:
        ds, ms, ys, de, me, ye = second.groups()
        return date(int(ys), int(ms), int(ds)), date(int(ye), int(me), int(de))

    third = re.search(
        r"(?:valido|válido|vigencia)[:\s]+(?:del\s+)?(\d{1,2})\s+de\s+([a-záéíóú]+)\s+(?:al|a)\s+(\d{1,2})\s+de\s+([a-záéíóú]+)(?:\s+de\s+(\d{4}))?",
        normalized,
    )
    if third:
        ds, ms_name, de, me_name, year_value = third.groups()
        year = int(year_value) if year_value else (fallback_year or date.today().year)
        ms = MONTHS.get(_strip_accents(ms_name))
        me = MONTHS.get(_strip_accents(me_name))
        if ms and me:
            return date(year, ms, int(ds)), date(year, me, int(de))

    single_end = re.search(r"(?:vto\.?|vence|valido hasta|v[aá]lido hasta|antes del)\s*(\d{1,2})/(\d{1,2})/(\d{4})", normalized)
    if single_end:
        day_value, month_value, year_value = single_end.groups()
        return None, date(int(year_value), int(month_value), int(day_value))

    return None, None


def extract_payment_method(text: str) -> str | None:
    lowered = text.lower()
    matches = []
    if "credito" in lowered or "crédito" in lowered:
        matches.append("credito")
    if "debito" in lowered or "débito" in lowered:
        matches.append("debito")
    if "qr" in lowered:
        matches.append("qr")
    if "ecommerce" in lowered or "online" in lowered or "vpos" in lowered:
        matches.append("ecommerce")
    return ",".join(matches) if matches else None


def extract_channel(text: str) -> str | None:
    lowered = text.lower()
    if "ecommerce" in lowered or "online" in lowered or "vpos" in lowered:
        return "ecommerce"
    if "qr" in lowered:
        return "qr"
    if "pos" in lowered or "caja" in lowered or "mostrador" in lowered:
        return "presencial"
    return None


def extract_card_scope(text: str) -> str | None:
    lowered = text.lower()
    scopes = []
    for label in ["black", "infinite", "signature", "premium", "personal bank", "clasica", "clásica", "albirroja"]:
        if label in lowered:
            scopes.append(label.replace("á", "a"))
    return ",".join(sorted(set(scopes))) if scopes else None


def extract_cap_amount(text: str) -> float | None:
    return _extract_amount(
        text,
        [
            r"tope(?: de)?\s+gs\.?\s*([\d\.\,]+)",
            r"maximo(?: de)?\s+gs\.?\s*([\d\.\,]+)",
            r"hasta\s+gs\.?\s*([\d\.\,]+)\s*(?:de ahorro|de reintegro|por compra|por cuenta)?",
        ],
    )


def extract_minimum_purchase(text: str) -> float | None:
    return _extract_amount(
        text,
        [
            r"compra minima\s+de\s+gs\.?\s*([\d\.\,]+)",
            r"minimo(?: de compra)?\s+gs\.?\s*([\d\.\,]+)",
            r"consumo minimo\s+de\s+gs\.?\s*([\d\.\,]+)",
        ],
    )


def extract_valid_days(text: str) -> list[str] | None:
    lowered = text.lower()
    found = [normalized for label, normalized in DAY_ALIASES.items() if label in lowered]
    return sorted(set(found)) or None


def extract_installments(text: str) -> int | None:
    matches = re.findall(r"(?:hasta\s+|\+)?(\d{1,2})\s+cuotas", text.lower())
    return max((int(item) for item in matches), default=None)


def extract_discount_percent(text: str) -> float | None:
    lowered = text.lower()
    patterns = [
        r"(\d{1,3})\s*%\s*(?:de\s+)?descuento",
        r"(\d{1,3})\s*%\s*en caja",
        r"hasta\s+(\d{1,3})\s*%\s*en\s+(?:combustible|supermercados|tiendas|farmacias|gastronomia|peluquerias?|spa)",
    ]
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            return float(match.group(1))
    return None


def extract_cashback_percent(text: str) -> float | None:
    matches = re.findall(r"(\d{1,3})\s*%\s*(?:de\s+)?(?:reintegro|cashback)", text.lower())
    return max((float(item) for item in matches), default=None)


def _extract_amount(text: str, patterns: list[str]) -> float | None:
    lowered = text.lower()
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            try:
                return float(match.group(1).replace(".", "").replace(",", "."))
            except ValueError:
                return None
    return None


def _strip_accents(value: str) -> str:
    return value.translate(str.maketrans("áéíóú", "aeiou"))
