from __future__ import annotations

from datetime import date

from models.compat import BaseModel, Field


class Promotion(BaseModel):
    bank: str
    card_brand: str | None = None
    card_tier: str | None = None
    title: str
    category: str | None = None
    merchant: str | None = None
    merchant_raw: str | None = None
    merchant_normalized: str | None = None
    brand_normalized: str | None = None
    merchant_aliases: list[str] = Field(default_factory=list)
    discount_percent: float | None = None
    cashback_percent: float | None = None
    installments: int | None = None
    benefit_type: str | None = None
    promo_mechanic: str | None = None
    payment_method: str | None = None
    channel: str | None = None
    card_scope: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    valid_days: list[str] | None = None
    cap_amount: float | None = None
    minimum_purchase_amount: float | None = None
    stackable: bool | None = None
    month_ref: str | None = None
    source_type: str
    source_url: str
    source_document: str | None = None
    summary: str | None = None
    raw_text: str
    confidence_score: float = 0.0


class FuelPrice(BaseModel):
    brand: str
    octane: int
    base_price: float
    captured_at: str
    source_url: str
    raw_text: str | None = None


class QueryMatch(BaseModel):
    merchant: str
    category: str | None = None
    bank: str | None = None
    benefit: str
    promo_type: str | None = None
    ranking_score: float | None = None
    result_quality_score: float | None = None
    result_quality_label: str | None = None
    price_base: float | None = None
    price_final_estimated: float | None = None
    valid_until: str | None = None
    source_url: str | None = None
    explanation: str
