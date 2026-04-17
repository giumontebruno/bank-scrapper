from datetime import date
from pathlib import Path

from models.promotion import Promotion
from query.repository import PromotionRepository


def test_replace_promotions_is_idempotent_by_bank_and_month(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")
    promotions = [
        Promotion(
            bank="Ueno",
            title="Shell",
            category="combustible",
            merchant="Shell",
            merchant_raw="Shell Mcal Lopez",
            merchant_normalized="Shell",
            brand_normalized="Shell",
            cashback_percent=20,
            end_date=date(2026, 4, 30),
            month_ref="2026-04",
            source_type="html_detail",
            source_url="https://example.com/shell",
            raw_text="20% Shell",
            confidence_score=0.9,
        )
    ]

    repository.replace_promotions("Ueno", "2026-04", promotions)
    repository.replace_promotions("Ueno", "2026-04", promotions)

    rows = repository.list_promotions()
    assert len(rows) == 1


def test_replace_promotions_keeps_other_banks_and_replaces_bnf_lot(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")
    repository.replace_promotions(
        "Continental",
        "2026-04",
        [
            Promotion(
                bank="Continental",
                title="Combustible",
                category="combustible",
                merchant=None,
                discount_percent=25,
                month_ref="2026-04",
                source_type="html_detail",
                source_url="https://example.com/continental",
                raw_text="25% combustible",
                confidence_score=0.8,
            )
        ],
    )
    repository.replace_promotions(
        "BNF",
        "2026-04",
        [
            Promotion(
                bank="BNF",
                title="Vale Petrobras",
                category="combustible",
                merchant="Petrobras",
                merchant_raw="Petrobras",
                merchant_normalized="Petrobras",
                brand_normalized="Petrobras",
                benefit_type="voucher",
                month_ref="2026-04",
                source_type="html_detail",
                source_url="https://example.com/bnf/petrobras",
                raw_text="Vale Petrobras",
                confidence_score=0.4,
            )
        ],
    )
    repository.replace_promotions(
        "BNF",
        "2026-04",
        [
            Promotion(
                bank="BNF",
                title="Vale Stock",
                category="supermercados",
                merchant="Stock",
                merchant_raw="Stock",
                merchant_normalized="Stock",
                brand_normalized="Stock",
                benefit_type="voucher",
                month_ref="2026-04",
                source_type="html_detail",
                source_url="https://example.com/bnf/stock",
                raw_text="Vale Stock",
                confidence_score=0.4,
            )
        ],
    )

    rows = repository.list_promotions()

    assert len(rows) == 2
    assert any(item.bank == "Continental" for item in rows)
    assert any(item.bank == "BNF" and item.merchant_normalized == "Stock" for item in rows)
