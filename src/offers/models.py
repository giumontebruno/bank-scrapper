from __future__ import annotations

from datetime import date

from models.compat import BaseModel, Field


class Offer(BaseModel):
    bank: str | None = None
    merchant_raw: str | None = None
    merchant_normalized: str | None = None
    merchant_group: str | None = None
    category: str | None = None
    subcategory: str | None = None
    benefit_type: str | None = None
    benefit_summary: str
    discount_percent: float | None = None
    cashback_percent: float | None = None
    installments: int | None = None
    cap_amount: float | None = None
    min_purchase_amount: float | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    valid_days: list[str] | None = None
    channels: list[str] = Field(default_factory=list)
    source_url: str | None = None
    source_type: str | None = None
    source_document: str | None = None
    source_family: str | None = None
    external_source_id: str | None = None
    confidence_score: float = 0.0
    offer_quality_score: float = 0.0
    offer_quality_label: str = "low"
    promo_type: str = "generic_benefit"
    is_generic: bool = False
    is_category_only: bool = False
    is_today_relevant: bool = True
    is_featured_candidate: bool = False
    source_count: int = 1
    source_promotion_titles: list[str] = Field(default_factory=list)
