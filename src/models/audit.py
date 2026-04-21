from __future__ import annotations

from models.compat import BaseModel, Field
from models.promotion import QueryMatch


class AuditIssue(BaseModel):
    level: str
    code: str
    message: str


class BankHealth(BaseModel):
    bank: str
    promotions_total: int = 0
    merchant_clear_count: int = 0
    merchant_null_count: int = 0
    category_only_count: int = 0
    voucher_like_count: int = 0
    average_confidence_score: float = 0.0


class FuelHealth(BaseModel):
    total_prices: int = 0
    by_octane: dict[str, int] = Field(default_factory=dict)
    by_brand: dict[str, int] = Field(default_factory=dict)


class QueryAuditResult(BaseModel):
    query: str
    total_matches: int = 0
    quality_distribution: dict[str, int] = Field(default_factory=dict)
    promo_type_distribution: dict[str, int] = Field(default_factory=dict)
    warnings: list[AuditIssue] = Field(default_factory=list)
    top_matches: list[QueryMatch] = Field(default_factory=list)


class DatasetAudit(BaseModel):
    month_ref: str | None = None
    bank_filter: str | None = None
    total_promotions: int = 0
    promotions_by_bank: dict[str, int] = Field(default_factory=dict)
    promotions_by_category: dict[str, int] = Field(default_factory=dict)
    promotions_by_bank_category: dict[str, dict[str, int]] = Field(default_factory=dict)
    top_merchants: dict[str, int] = Field(default_factory=dict)
    top_merchants_by_category: dict[str, dict[str, int]] = Field(default_factory=dict)
    covered_categories: list[str] = Field(default_factory=list)
    weak_categories: list[str] = Field(default_factory=list)
    promo_type_distribution: dict[str, int] = Field(default_factory=dict)
    quality_distribution: dict[str, int] = Field(default_factory=dict)
    merchant_null_count: int = 0
    merchant_generic_or_missing_count: int = 0
    suspicious_merchant_count: int = 0
    merchant_clear_count: int = 0
    category_only_count: int = 0
    average_quality_score: float = 0.0
    canonical_offers_total: int = 0
    duplicated_promotions_consolidated: int = 0
    featured_candidate_count: int = 0
    generic_offer_count: int = 0
    canonical_category_only_count: int = 0
    suspicious_merchants: dict[str, int] = Field(default_factory=dict)
    banks: list[BankHealth] = Field(default_factory=list)
    fuel: FuelHealth = Field(default_factory=FuelHealth)


class AuditReport(BaseModel):
    dataset: DatasetAudit
    api_readiness: str = "warning"
    api_readiness_reasons: list[str] = Field(default_factory=list)
    issues: list[AuditIssue] = Field(default_factory=list)
    smoke_queries: list[QueryAuditResult] = Field(default_factory=list)
