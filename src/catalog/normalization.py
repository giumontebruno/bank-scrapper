from __future__ import annotations

import re

from models.compat import BaseModel, Field
from utils.text import normalize_text

BRAND_RULES: dict[str, list[str]] = {
    "Shell": ["shell"],
    "Copetrol": ["copetrol", "copetrol sa"],
    "Petropar": ["petropar"],
    "Petrobras": ["petrobras", "petrosur"],
    "Enex": ["enex"],
    "Superseis": ["superseis", "super seis", "super 6"],
    "Stock": ["stock"],
    "Biggie": ["biggie", "biggie express"],
    "Ferrex": ["ferrex"],
    "Ferreteria Don Juan": ["ferreteria don juan", "ferreteria donjuan", "don juan"],
}

LOCATION_STOPWORDS = {
    "bahia",
    "palma",
    "mcal lopez",
    "mariscal lopez",
    "acceso sur",
    "molas lopez",
    "sajonia",
    "villamorra",
}

GENERIC_MERCHANT_TERMS = {
    "beneficios",
    "promociones",
    "promocion",
    "campana valida",
    "campaña valida",
    "campana válida",
    "campaña válida",
    "ver bases y condiciones",
    "medios de pago habilitados",
    "disfruta tus rubros favoritos en cuotas",
    "comercios beneficio",
    "mastercard debit",
    "conocer promos",
    "conoce mas",
    "conoce mas sobre ueno",
    "ver mas",
    "descubri",
    "descubri mas",
    "descubri beneficios",
    "canjea",
    "canjear",
    "medios de pago",
    "disfruta tus rubros",
    "comercios beneficio",
    "reintegro",
    "en caja reintegro",
    "intereses",
    "sin intereses",
    "locales adheridos",
    "de tiendas",
    "estaciones adheridas",
    "en estaciones adheridas",
    "todos los comercios adheridos",
    "aplica a comercios seleccionados",
    "aplica a locales seleccionados",
    "locales seleccionados",
    "comercios adheridos",
    "plazo de acreditacion del reintegro",
    "notificaciones en la aplicacion movil del banco",
    "supermercados",
    "supermercado",
    "super",
    "combustible",
    "farmacias",
    "farmacia",
    "tiendas",
    "gastronomia",
    "gastronomía",
    "ferreteria",
    "ferretería",
    "hogar",
    "retail",
    "salud",
    "entretenimiento",
    "viajes",
    "otros",
    "exclusivo pos",
    "exclusivamente los dias jueves",
    "las series a y b",
    "ueno bank",
    "ueno bank a",
    "ueno bank s a",
    "banco itau",
    "itau paraguay",
    "itau",
    "...",
}

GENERIC_PREFIXES = (
    "no aplica",
    "ver bases",
    "bases y condiciones",
    "aplica a",
    "todos los",
    "todas las",
    "campana",
    "campaña",
    "vigencia",
    "vto",
    "hasta ",
    "compra minima",
    "consumo minimo",
    "beneficio",
    "promocion",
    "promociones",
    "conocer promos",
    "conoce mas",
    "conoce mas sobre",
    "ver mas",
    "descubri",
    "descubri mas",
    "canjea",
    "canjear",
    "reintegro",
    "en caja",
    "de ",
    "en estaciones adheridas",
    "estaciones adheridas",
    "intereses",
    "sin intereses",
    "descargar",
    "click",
    "las series",
    "exclusivamente los dias",
    "ueno bank",
    "banco ",
)

DAY_PREFIXES = ("lunes", "martes", "miercoles", "miércoles", "jueves", "viernes", "sabado", "sábado", "domingo")


class MerchantResolution(BaseModel):
    merchant_raw: str | None = None
    merchant_normalized: str | None = None
    brand_normalized: str | None = None
    aliases: list[str] = Field(default_factory=list)


class MerchantAssessment(BaseModel):
    raw_name: str | None = None
    cleaned_name: str | None = None
    is_valid: bool = False
    quality: str = "low"
    reason: str | None = None


def resolve_merchant(raw_name: str | None) -> MerchantResolution:
    assessment = assess_merchant_candidate(raw_name)
    if not assessment.is_valid or not assessment.cleaned_name:
        return MerchantResolution(merchant_raw=raw_name)

    normalized = normalize_text(assessment.cleaned_name)
    compact = _strip_noise(normalized)

    for canonical, aliases in BRAND_RULES.items():
        alias_set = {normalize_text(alias) for alias in aliases}
        if compact in alias_set or any(alias in compact for alias in alias_set):
            return MerchantResolution(
                merchant_raw=raw_name,
                merchant_normalized=canonical,
                brand_normalized=canonical,
                aliases=sorted(alias_set),
            )

    return MerchantResolution(
        merchant_raw=raw_name,
        merchant_normalized=_titleize(compact),
        brand_normalized=None,
        aliases=[compact] if compact else [],
    )


def merchant_equivalent(left: str | None, right: str | None) -> bool:
    left_resolution = resolve_merchant(left)
    right_resolution = resolve_merchant(right)
    if not left_resolution.merchant_normalized or not right_resolution.merchant_normalized:
        return False
    if left_resolution.brand_normalized and left_resolution.brand_normalized == right_resolution.brand_normalized:
        return True
    return left_resolution.merchant_normalized == right_resolution.merchant_normalized


def assess_merchant_candidate(raw_name: str | None) -> MerchantAssessment:
    if not raw_name:
        return MerchantAssessment(raw_name=raw_name, reason="empty")

    cleaned_original = re.sub(r"\s+", " ", raw_name).strip(" -•\t\r\n")
    normalized = normalize_text(cleaned_original)
    compact = _strip_noise(normalized)
    repeated_compact = _collapse_repeated_letters(compact)

    if not compact:
        return MerchantAssessment(raw_name=raw_name, reason="empty_after_clean")
    if len(compact) < 3:
        return MerchantAssessment(raw_name=raw_name, cleaned_name=cleaned_original, reason="too_short")

    for canonical, aliases in BRAND_RULES.items():
        alias_set = {normalize_text(alias) for alias in aliases}
        if compact in alias_set or any(alias in compact for alias in alias_set):
            return MerchantAssessment(
                raw_name=raw_name,
                cleaned_name=canonical,
                is_valid=True,
                quality="high",
            )

    # Algunas marcas reales usan numeros en el nombre comercial; si no hicieron match arriba,
    # tratamos esos casos como poco confiables para evitar capturar porcentajes o CTAs como merchant.
    if any(char.isdigit() for char in compact) or "%" in cleaned_original:
        return MerchantAssessment(raw_name=raw_name, cleaned_name=cleaned_original, reason="contains_numeric_or_percent")
    if len(compact) > 70 or len(compact.split()) > 8:
        return MerchantAssessment(raw_name=raw_name, cleaned_name=cleaned_original, reason="too_long")
    if compact in GENERIC_MERCHANT_TERMS or repeated_compact in GENERIC_MERCHANT_TERMS:
        return MerchantAssessment(raw_name=raw_name, cleaned_name=cleaned_original, reason="generic_term")
    if compact.startswith(GENERIC_PREFIXES) or compact.startswith(DAY_PREFIXES) or repeated_compact.startswith(GENERIC_PREFIXES):
        return MerchantAssessment(raw_name=raw_name, cleaned_name=cleaned_original, reason="generic_prefix")
    if any(phrase in compact or phrase in repeated_compact for phrase in GENERIC_MERCHANT_TERMS if len(phrase.split()) > 1):
        return MerchantAssessment(raw_name=raw_name, cleaned_name=cleaned_original, reason="generic_phrase")
    if any(
        token in compact
        for token in [
            "bases",
            "condiciones",
            "giftcard",
            "domicilio",
            "usuarios",
            "detalle",
            "locales seleccionados",
            "comercios adheridos",
            "locales adheridos",
            "conocer",
            "conoce",
            "descubri",
            "canjea",
            "canjear",
            "ver mas",
            "medios de pago",
            "disfruta tus rubros",
            "comercios beneficio",
            "plazo de acreditacion",
            "notificaciones",
            "aplicacion movil del banco",
            "ueno bank",
            "las series",
            "exclusivamente los dias",
        ]
    ):
        return MerchantAssessment(raw_name=raw_name, cleaned_name=cleaned_original, reason="disclaimer_or_navigation")

    return MerchantAssessment(
        raw_name=raw_name,
        cleaned_name=_titleize(compact),
        is_valid=True,
        quality="medium",
    )


def find_merchant_hint(text: str, allowed_hints: list[str] | tuple[str, ...]) -> str | None:
    normalized = normalize_text(text)
    candidates: list[tuple[int, str]] = []
    for hint in allowed_hints:
        hint_normalized = normalize_text(hint)
        if hint_normalized in GENERIC_MERCHANT_TERMS:
            continue
        position = normalized.find(hint_normalized)
        if position >= 0:
            candidates.append((position, hint))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], -len(item[1])))
    return candidates[0][1]


def _strip_noise(value: str) -> str:
    cleaned = re.sub(r"\b(sa|s\.a\.|srl|shop|express)\b", " ", value)
    for location in LOCATION_STOPWORDS:
        cleaned = cleaned.replace(location, " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def _collapse_repeated_letters(value: str) -> str:
    return re.sub(r"([a-z])\1{2,}", r"\1", value)


def _titleize(value: str) -> str:
    return " ".join(part.capitalize() for part in value.split())
