from __future__ import annotations

from collections import Counter, defaultdict

from catalog.data import IMPORTANT_CATEGORIES
from catalog.service import CatalogService
from catalog.normalization import assess_merchant_candidate
from models.audit import AuditIssue, AuditReport, BankHealth, DatasetAudit, FuelHealth, QueryAuditResult
from models.promotion import FuelPrice, Promotion, QueryMatch
from offers import build_offer_catalog, load_supplemental_offer_sources
from query.engine import QueryEngine
from query.ranking import infer_promo_type, result_quality
from query.repository import PromotionRepository

DEFAULT_SMOKE_QUERIES = [
    "que tarjeta me conviene para 97",
    "que tarjeta me conviene para 95",
    "quiero comprar en super",
    "quiero ver promos de ropa",
    "quiero comprar tecnologia",
    "quiero salir a comer",
    "quiero comprar en farmacia",
    "hoy necesito comprar clavos",
    "que banco me conviene hoy",
]

SUPPORTED_BANKS = ["Ueno", "Itau", "Sudameris", "Continental", "BNF"]


class _AuditRepositoryView:
    def __init__(self, promotions: list[Promotion], fuel_prices: list[FuelPrice]) -> None:
        self._promotions = promotions
        self._fuel_prices = fuel_prices

    def list_promotions(self) -> list[Promotion]:
        return list(self._promotions)

    def list_fuel_prices(self) -> list[FuelPrice]:
        return list(self._fuel_prices)


def build_audit_report(
    repository: PromotionRepository,
    *,
    month_ref: str | None = None,
    bank: str | None = None,
    queries: list[str] | None = None,
) -> AuditReport:
    promotions = _filter_promotions(repository.list_promotions(), month_ref=month_ref, bank=bank)
    fuel_prices = repository.list_fuel_prices()
    dataset = summarize_dataset(promotions, fuel_prices, month_ref=month_ref, bank=bank)
    smoke_queries = run_smoke_queries(promotions, fuel_prices, queries=queries or DEFAULT_SMOKE_QUERIES)
    issues = collect_audit_issues(dataset, smoke_queries)
    readiness, reasons = determine_api_readiness(dataset, smoke_queries)
    return AuditReport(
        dataset=dataset,
        api_readiness=readiness,
        api_readiness_reasons=reasons,
        issues=issues,
        smoke_queries=smoke_queries,
    )


def summarize_dataset(
    promotions: list[Promotion],
    fuel_prices: list[FuelPrice],
    *,
    month_ref: str | None = None,
    bank: str | None = None,
) -> DatasetAudit:
    promo_type_counts: Counter[str] = Counter()
    quality_counts: Counter[str] = Counter()
    promotions_by_bank: Counter[str] = Counter()
    promotions_by_category: Counter[str] = Counter()
    top_merchants: Counter[str] = Counter()
    top_merchants_by_category: dict[str, Counter[str]] = defaultdict(Counter)
    promotions_by_bank_category: dict[str, Counter[str]] = defaultdict(Counter)
    suspicious_merchants: Counter[str] = Counter()
    quality_total = 0.0
    merchant_null_count = 0
    merchant_generic_or_missing_count = 0
    suspicious_merchant_count = 0
    merchant_clear_count = 0
    category_only_count = 0
    bank_buckets: dict[str, list[Promotion]] = defaultdict(list)
    offers = build_offer_catalog(promotions, supplemental_sources=load_supplemental_offer_sources())

    for promotion in promotions:
        bank_buckets[promotion.bank].append(promotion)
        promotions_by_bank[promotion.bank] += 1
        if promotion.category:
            promotions_by_category[promotion.category] += 1
            promotions_by_bank_category[promotion.bank][promotion.category] += 1

        promo_type = infer_promo_type(promotion)
        promo_type_counts[promo_type] += 1
        quality_score, quality_label = result_quality(promotion, None, promo_type=promo_type)
        quality_counts[quality_label] += 1
        quality_total += quality_score

        has_clear_merchant = bool(promotion.brand_normalized or promotion.merchant_normalized)
        if has_clear_merchant:
            merchant_clear_count += 1
            merchant_name = promotion.brand_normalized or promotion.merchant_normalized or ""
            top_merchants[merchant_name] += 1
            if promotion.category:
                top_merchants_by_category[promotion.category][merchant_name] += 1
            if _is_suspicious_clear_merchant(merchant_name):
                suspicious_merchant_count += 1
                suspicious_merchants[merchant_name] += 1
        else:
            merchant_null_count += 1
            if promotion.category:
                category_only_count += 1
        if _is_missing_or_generic_merchant(promotion):
            merchant_generic_or_missing_count += 1

    bank_health = [_build_bank_health(bank_name, items) for bank_name, items in sorted(bank_buckets.items())]
    fuel_health = _build_fuel_health(fuel_prices)
    average_quality_score = round(quality_total / len(promotions), 4) if promotions else 0.0
    covered_categories = [category for category in IMPORTANT_CATEGORIES if promotions_by_category.get(category, 0) > 0]
    weak_categories = [category for category in IMPORTANT_CATEGORIES if promotions_by_category.get(category, 0) <= 1]

    return DatasetAudit(
        month_ref=month_ref,
        bank_filter=bank,
        total_promotions=len(promotions),
        promotions_by_bank=dict(sorted(promotions_by_bank.items())),
        promotions_by_category=dict(promotions_by_category.most_common()),
        promotions_by_bank_category={
            bank_name: dict(counter.most_common()) for bank_name, counter in sorted(promotions_by_bank_category.items())
        },
        top_merchants=dict(top_merchants.most_common(10)),
        top_merchants_by_category={
            category: dict(counter.most_common(5)) for category, counter in sorted(top_merchants_by_category.items())
        },
        covered_categories=covered_categories,
        weak_categories=weak_categories,
        promo_type_distribution=dict(sorted(promo_type_counts.items())),
        quality_distribution=dict(sorted(quality_counts.items())),
        merchant_null_count=merchant_null_count,
        merchant_generic_or_missing_count=merchant_generic_or_missing_count,
        suspicious_merchant_count=suspicious_merchant_count,
        merchant_clear_count=merchant_clear_count,
        category_only_count=category_only_count,
        average_quality_score=average_quality_score,
        canonical_offers_total=len(offers),
        duplicated_promotions_consolidated=max(0, len(promotions) - len(offers)),
        featured_candidate_count=sum(1 for offer in offers if offer.is_featured_candidate),
        generic_offer_count=sum(1 for offer in offers if offer.is_generic),
        canonical_category_only_count=sum(1 for offer in offers if offer.is_category_only),
        suspicious_merchants=dict(suspicious_merchants.most_common(10)),
        banks=bank_health,
        fuel=fuel_health,
    )


def run_smoke_queries(
    promotions: list[Promotion],
    fuel_prices: list[FuelPrice],
    *,
    queries: list[str],
) -> list[QueryAuditResult]:
    engine = QueryEngine(_AuditRepositoryView(promotions, fuel_prices))
    catalog = CatalogService()
    results: list[QueryAuditResult] = []
    for query in queries:
        payload = engine.query(query)
        matches = payload["matches"]
        inferred_category = catalog.infer_category(query)
        quality_counts: Counter[str] = Counter()
        promo_type_counts: Counter[str] = Counter()
        warnings: list[AuditIssue] = []

        for item in matches:
            quality_counts[item.get("result_quality_label") or "fallback"] += 1
            promo_type_counts[item.get("promo_type") or "catalog_fallback"] += 1

        if matches and all(item.get("promo_type") == "catalog_fallback" for item in matches):
            if inferred_category:
                warnings.append(
                    AuditIssue(
                        level="warning",
                        code="no_live_promos_for_category",
                        message=(
                            f"La query '{query}' no tiene promo real para {inferred_category}; "
                            "solo hubo coincidencia de rubro por catálogo."
                        ),
                    )
                )
            else:
                warnings.append(
                    AuditIssue(
                        level="warning",
                        code="query_only_fallback",
                        message=f"La query '{query}' devolvio solo fallback de catalogo.",
                    )
                )
        if "97" in query or "95" in query or "combustible" in query:
            if not any(item.get("price_base") is not None for item in matches):
                warnings.append(
                    AuditIssue(
                        level="warning",
                        code="fuel_query_without_base_price",
                        message=f"La query '{query}' no devolvio precio base de combustible.",
                    )
                )
        if _looks_broad_query(query):
            top_slice = matches[:3]
            weak_top = [item for item in top_slice if item.get("result_quality_label") in {"low", "fallback"}]
            if len(top_slice) >= 2 and len(weak_top) >= 2:
                warnings.append(
                    AuditIssue(
                        level="warning",
                        code="broad_query_weak_top_results",
                        message=f"La query amplia '{query}' muestra demasiados resultados low/fallback arriba.",
                    )
                )

        results.append(
            QueryAuditResult(
                query=query,
                total_matches=len(matches),
                quality_distribution=dict(sorted(quality_counts.items())),
                promo_type_distribution=dict(sorted(promo_type_counts.items())),
                warnings=warnings,
                top_matches=[QueryMatch.parse_obj(item) for item in matches[:5]],
            )
        )
    return results


def collect_audit_issues(dataset: DatasetAudit, smoke_queries: list[QueryAuditResult]) -> list[AuditIssue]:
    issues: list[AuditIssue] = []

    for bank_name in SUPPORTED_BANKS:
        count = dataset.promotions_by_bank.get(bank_name, 0)
        if count == 0 and (dataset.bank_filter is None or dataset.bank_filter.lower() == bank_name.lower()):
            issues.append(
                AuditIssue(
                    level="warning",
                    code="bank_without_promotions",
                    message=f"{bank_name} quedo con 0 promociones en el dataset auditado.",
                )
            )

    if dataset.fuel.total_prices == 0:
        issues.append(
            AuditIssue(
                level="warning",
                code="fuel_prices_empty",
                message="Fuel prices quedo con 0 filas; las queries de combustible perderan price_base.",
            )
        )

    if dataset.total_promotions == 0:
        issues.append(
            AuditIssue(
                level="error",
                code="dataset_without_promotions",
                message="No hay promociones persistidas para el corte auditado.",
            )
        )

    if dataset.total_promotions > 0:
        null_ratio = dataset.merchant_generic_or_missing_count / dataset.total_promotions
        if null_ratio >= 0.45:
            issues.append(
                AuditIssue(
                    level="warning",
                    code="merchant_quality_degraded",
                    message="El porcentaje de promos sin merchant claro o generico es alto.",
                )
            )
    if dataset.suspicious_merchant_count > 0:
        issues.append(
            AuditIssue(
                level="warning",
                code="suspicious_normalized_merchants",
                message="Hay merchants normalizados sospechosos; conviene revisar parsing o rerunear el banco afectado.",
            )
        )
    if dataset.weak_categories:
        issues.append(
            AuditIssue(
                level="warning",
                code="weak_category_coverage",
                message=(
                    "La cobertura por categoría sigue débil en: "
                    + ", ".join(dataset.weak_categories)
                    + "."
                ),
            )
        )
    if set(dataset.fuel.by_octane) - {"95", "97"}:
        issues.append(
            AuditIssue(
                level="warning",
                code="fuel_octane_mismatch",
                message="El dataset de combustible contiene octanajes fuera de 95 y 97.",
            )
        )

    for result in smoke_queries:
        issues.extend(result.warnings)

    return issues


def render_audit_report(report: AuditReport) -> str:
    lines: list[str] = []
    dataset = report.dataset
    lines.append("== Dataset ==")
    lines.append(f"month_ref: {dataset.month_ref or 'todos'}")
    lines.append(f"bank_filter: {dataset.bank_filter or 'todos'}")
    lines.append(f"promotions_total: {dataset.total_promotions}")
    lines.append(f"fuel_prices_total: {dataset.fuel.total_prices}")
    lines.append(f"average_quality_score: {dataset.average_quality_score}")
    lines.append(f"api_readiness: {report.api_readiness}")
    if report.api_readiness_reasons:
        lines.append(f"api_readiness_reasons: {report.api_readiness_reasons}")
    lines.append("")
    lines.append("== Promotions by bank ==")
    for bank_name, count in dataset.promotions_by_bank.items():
        lines.append(f"- {bank_name}: {count}")
    lines.append("")
    lines.append("== Coverage by category ==")
    for category, count in dataset.promotions_by_category.items():
        lines.append(f"- {category}: {count}")
    lines.append(f"- covered_categories: {dataset.covered_categories}")
    lines.append(f"- weak_categories: {dataset.weak_categories}")
    lines.append("")
    lines.append("== Coverage by bank/category ==")
    for bank_name, counters in dataset.promotions_by_bank_category.items():
        lines.append(f"- {bank_name}: {counters}")
    lines.append("")
    lines.append("== Merchant health ==")
    lines.append(f"- clear: {dataset.merchant_clear_count}")
    lines.append(f"- null: {dataset.merchant_null_count}")
    lines.append(f"- generic_or_missing: {dataset.merchant_generic_or_missing_count}")
    lines.append(f"- suspicious_clear: {dataset.suspicious_merchant_count}")
    lines.append(f"- category_only: {dataset.category_only_count}")
    lines.append("")
    lines.append("== Canonical offers ==")
    lines.append(f"- canonical_offers_total: {dataset.canonical_offers_total}")
    lines.append(f"- duplicated_promotions_consolidated: {dataset.duplicated_promotions_consolidated}")
    lines.append(f"- featured_candidates: {dataset.featured_candidate_count}")
    lines.append(f"- generic_offers: {dataset.generic_offer_count}")
    lines.append(f"- category_only_offers: {dataset.canonical_category_only_count}")
    lines.append("")
    lines.append("== Promo types ==")
    for key, value in dataset.promo_type_distribution.items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("== Quality labels ==")
    for key, value in dataset.quality_distribution.items():
        lines.append(f"- {key}: {value}")
    lines.append("== Top merchants ==")
    for key, value in dataset.top_merchants.items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("== Top merchants by category ==")
    for category, merchants in dataset.top_merchants_by_category.items():
        lines.append(f"- {category}: {merchants}")
    if dataset.suspicious_merchants:
        lines.append("")
        lines.append("== Suspicious merchants ==")
        for key, value in dataset.suspicious_merchants.items():
            lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("== Fuel prices ==")
    for key, value in dataset.fuel.by_octane.items():
        lines.append(f"- octane {key}: {value}")
    for key, value in dataset.fuel.by_brand.items():
        lines.append(f"- brand {key}: {value}")
    lines.append("")
    lines.append("== Issues ==")
    if report.issues:
        for item in report.issues:
            lines.append(f"- [{item.level}] {item.code}: {item.message}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("== Smoke queries ==")
    for result in report.smoke_queries:
        lines.append(f"- query: {result.query}")
        lines.append(f"  total_matches: {result.total_matches}")
        lines.append(f"  quality: {result.quality_distribution}")
        lines.append(f"  promo_types: {result.promo_type_distribution}")
        for item in result.top_matches[:5]:
            lines.append(
                f"  * {item.merchant} | bank={item.bank or '-'} | benefit={item.benefit} | "
                f"quality={item.result_quality_label} | promo_type={item.promo_type} | "
                f"price_base={item.price_base} | final={item.price_final_estimated}"
            )
        for warning in result.warnings:
            lines.append(f"  ! [{warning.level}] {warning.code}: {warning.message}")
    return "\n".join(lines)


def determine_api_readiness(dataset: DatasetAudit, smoke_queries: list[QueryAuditResult]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    banks_missing = [bank for bank in SUPPORTED_BANKS if dataset.promotions_by_bank.get(bank, 0) == 0]
    has_suspicious = dataset.suspicious_merchant_count > 0
    query_warnings = [warning.code for result in smoke_queries for warning in result.warnings]

    if dataset.fuel.total_prices == 0:
        reasons.append("fuel_prices_empty")
    if len(banks_missing) > 2:
        reasons.append("too_many_banks_without_promotions")
    if set(dataset.fuel.by_octane) - {"95", "97"}:
        reasons.append("fuel_octane_mismatch")
    if reasons:
        return "blocked", reasons

    if banks_missing:
        reasons.append(f"banks_without_promotions:{','.join(banks_missing)}")
    if has_suspicious:
        reasons.append("suspicious_normalized_merchants")
    if query_warnings:
        reasons.extend(sorted(set(query_warnings)))

    if reasons:
        return "warning", reasons
    return "ready", []


def _filter_promotions(promotions: list[Promotion], *, month_ref: str | None, bank: str | None) -> list[Promotion]:
    items = promotions
    if month_ref is not None:
        items = [item for item in items if item.month_ref == month_ref]
    if bank is not None:
        bank_normalized = bank.lower()
        items = [item for item in items if item.bank.lower() == bank_normalized]
    return items


def _build_bank_health(bank_name: str, promotions: list[Promotion]) -> BankHealth:
    merchant_clear_count = 0
    merchant_null_count = 0
    category_only_count = 0
    voucher_like_count = 0
    total_confidence = 0.0
    for promotion in promotions:
        total_confidence += promotion.confidence_score or 0.0
        if promotion.brand_normalized or promotion.merchant_normalized:
            merchant_clear_count += 1
        else:
            merchant_null_count += 1
            if promotion.category:
                category_only_count += 1
        if infer_promo_type(promotion) in {"voucher", "loyalty_reward"}:
            voucher_like_count += 1

    return BankHealth(
        bank=bank_name,
        promotions_total=len(promotions),
        merchant_clear_count=merchant_clear_count,
        merchant_null_count=merchant_null_count,
        category_only_count=category_only_count,
        voucher_like_count=voucher_like_count,
        average_confidence_score=round(total_confidence / len(promotions), 4) if promotions else 0.0,
    )


def _build_fuel_health(fuel_prices: list[FuelPrice]) -> FuelHealth:
    by_octane = Counter(str(item.octane) for item in fuel_prices)
    by_brand = Counter(item.brand for item in fuel_prices)
    return FuelHealth(
        total_prices=len(fuel_prices),
        by_octane=dict(sorted(by_octane.items())),
        by_brand=dict(sorted(by_brand.items())),
    )


def _is_missing_or_generic_merchant(promotion: Promotion) -> bool:
    if promotion.brand_normalized or promotion.merchant_normalized:
        return False
    if not promotion.merchant and promotion.category:
        return True
    assessment = assess_merchant_candidate(promotion.merchant_raw or promotion.merchant)
    return not assessment.is_valid


def _is_suspicious_clear_merchant(merchant_name: str) -> bool:
    assessment = assess_merchant_candidate(merchant_name)
    return not assessment.is_valid


def _looks_broad_query(text: str) -> bool:
    normalized = text.lower()
    broad_phrases = [
        "que banco me conviene hoy",
        "quiero promociones",
        "quiero ver beneficios",
        "beneficios",
        "promociones",
    ]
    return any(phrase in normalized for phrase in broad_phrases)
