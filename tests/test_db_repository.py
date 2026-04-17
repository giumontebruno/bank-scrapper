from __future__ import annotations

from datetime import date
from pathlib import Path

from models.promotion import FuelPrice, Promotion
from query.repository import PromotionRepository


def test_repository_supports_sqlalchemy_sqlite_url(tmp_path: Path) -> None:
    repository = PromotionRepository(f"sqlite:///{(tmp_path / 'remote-like.sqlite').as_posix()}")
    repository.save_promotions(
        [
            Promotion(
                bank="Continental",
                title="Promo Stock",
                category="supermercados",
                merchant="Stock",
                merchant_raw="Stock",
                merchant_normalized="Stock",
                brand_normalized="Stock",
                cashback_percent=20,
                end_date=date(2026, 4, 30),
                month_ref="2026-04",
                source_type="html_detail",
                source_url="https://example.com/stock",
                raw_text="20% en Stock",
                confidence_score=0.8,
            )
        ]
    )
    repository.save_fuel_prices(
        [
            FuelPrice(
                brand="Shell",
                octane=95,
                base_price=7320,
                captured_at="2026-04-17T00:00:00+00:00",
                source_url="https://www.combustibles.com.py/",
            )
        ]
    )

    assert repository.backend == "sqlite"
    assert len(repository.list_promotions(month_ref="2026-04")) == 1
    assert repository.list_fuel_prices()[0].octane == 95
