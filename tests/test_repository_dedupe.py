from datetime import date
from pathlib import Path

from models.promotion import Promotion
from query.repository import PromotionRepository


def test_repository_dedupes_logical_duplicates_between_sources(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")
    repository.save_promotions(
        [
            Promotion(
                bank="Ueno",
                title="Promo Shell",
                merchant="Shell Bahia",
                merchant_raw="Shell Bahia",
                merchant_normalized="Shell",
                brand_normalized="Shell",
                category="combustible",
                discount_percent=20,
                end_date=date(2026, 4, 30),
                source_type="html_listing",
                source_url="https://example.com/listing",
                raw_text="20% en Shell",
                confidence_score=0.4,
            ),
            Promotion(
                bank="Ueno",
                title="Promo Shell detalle",
                merchant="Shell",
                merchant_raw="Shell",
                merchant_normalized="Shell",
                brand_normalized="Shell",
                category="combustible",
                discount_percent=20,
                end_date=date(2026, 4, 30),
                source_type="pdf_campaign",
                source_url="https://example.com/campaign",
                raw_text="20% en Shell con mas detalle",
                confidence_score=0.9,
            ),
        ]
    )

    promotions = repository.list_promotions()
    assert len(promotions) == 1
    assert promotions[0].source_type == "pdf_campaign"


def test_repository_keeps_distinct_continental_variants_when_terms_change(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")
    repository.save_promotions(
        [
            Promotion(
                bank="Continental",
                title="Promo Stock HTML",
                merchant="Stock",
                merchant_raw="Stock",
                merchant_normalized="Stock",
                brand_normalized="Stock",
                category="supermercados",
                cashback_percent=20,
                cap_amount=120000,
                valid_days=["friday"],
                end_date=date(2026, 4, 30),
                source_type="html_listing",
                source_url="https://example.com/stock-html",
                raw_text="20% viernes tope 120000",
                confidence_score=0.7,
            ),
            Promotion(
                bank="Continental",
                title="Promo Stock PDF",
                merchant="Stock",
                merchant_raw="Stock",
                merchant_normalized="Stock",
                brand_normalized="Stock",
                category="supermercados",
                cashback_percent=20,
                cap_amount=120000,
                valid_days=["friday"],
                end_date=date(2026, 4, 30),
                source_type="pdf_campaign",
                source_url="https://example.com/stock-pdf",
                raw_text="20% viernes tope 120000 bases",
                confidence_score=0.9,
            ),
            Promotion(
                bank="Continental",
                title="Promo Stock domingo",
                merchant="Stock",
                merchant_raw="Stock",
                merchant_normalized="Stock",
                brand_normalized="Stock",
                category="supermercados",
                cashback_percent=20,
                cap_amount=120000,
                valid_days=["sunday"],
                end_date=date(2026, 4, 30),
                source_type="pdf_campaign",
                source_url="https://example.com/stock-domingo",
                raw_text="20% domingo tope 120000 bases",
                confidence_score=0.9,
            ),
        ]
    )

    promotions = repository.list_promotions()
    assert len(promotions) == 2
    assert {tuple(item.valid_days or []) for item in promotions} == {("friday",), ("sunday",)}
