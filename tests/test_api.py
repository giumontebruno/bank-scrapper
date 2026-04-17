from __future__ import annotations

import importlib
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from core.config import reset_settings_cache
from models.promotion import FuelPrice, Promotion
from query.repository import PromotionRepository


def _seed_repository(path: Path) -> PromotionRepository:
    repository = PromotionRepository(path)
    repository.save_promotions(
        [
            Promotion(
                bank="Ueno",
                title="Promo Biggie",
                category="supermercados",
                merchant="Biggie",
                merchant_raw="Biggie",
                merchant_normalized="Biggie",
                brand_normalized="Biggie",
                cashback_percent=20,
                month_ref="2026-04",
                source_type="html_detail",
                source_url="https://example.com/ueno/biggie",
                raw_text="20% de reintegro en Biggie",
                confidence_score=0.8,
            ),
            Promotion(
                bank="Sudameris",
                title="Promo Copetrol",
                category="combustible",
                merchant="Copetrol",
                merchant_raw="Copetrol",
                merchant_normalized="Copetrol",
                brand_normalized="Copetrol",
                cashback_percent=25,
                end_date=date(2026, 4, 30),
                month_ref="2026-04",
                source_type="html_detail",
                source_url="https://example.com/sudameris/copetrol",
                raw_text="25% de reintegro en Copetrol",
                confidence_score=0.9,
            ),
        ]
    )
    repository.save_fuel_prices(
        [
            FuelPrice(
                brand="Copetrol",
                octane=97,
                base_price=10000,
                captured_at="2026-04-17T00:00:00+00:00",
                source_url="https://www.combustibles.com.py/",
            )
        ]
    )
    return repository


def test_api_endpoints_return_stable_json(monkeypatch, tmp_path: Path) -> None:
    repository = _seed_repository(tmp_path / "catalog.sqlite")
    import api.main as api_main

    monkeypatch.setattr(api_main, "get_repository", lambda: repository)
    client = TestClient(api_main.app)

    health = client.get("/health")
    audit = client.get("/audit", params={"month": "2026-04", "query": "que tarjeta me conviene para 97"})
    query = client.get("/query", params={"text": "que tarjeta me conviene para 97"})
    banks = client.get("/banks", params={"month": "2026-04"})
    fuels = client.get("/fuel-prices", params={"month": "2026-04"})
    promotions = client.get("/promotions", params={"month": "2026-04", "category": "combustible"})
    categories = client.get("/categories", params={"month": "2026-04"})

    assert health.status_code == 200
    assert health.json()["database_backend"] == "sqlite"
    assert audit.status_code == 200
    assert "dataset" in audit.json()
    assert query.status_code == 200
    assert query.json()["matches"]
    assert banks.status_code == 200
    assert "counts" in banks.json()
    assert fuels.status_code == 200
    assert fuels.json()["items"][0]["brand"] == "Copetrol"
    assert promotions.status_code == 200
    assert promotions.json()["count"] == 1
    assert categories.status_code == 200
    assert "covered_categories" in categories.json()


def test_api_admin_collect_and_audit(monkeypatch, tmp_path: Path) -> None:
    repository = _seed_repository(tmp_path / "catalog.sqlite")
    import api.main as api_main

    monkeypatch.setattr(api_main, "get_repository", lambda: repository)
    monkeypatch.setattr(api_main, "_ensure_admin_enabled", lambda settings: None)
    monkeypatch.setattr(
        api_main,
        "run_collect",
        lambda repo, month, bank=None: {
            "month": month,
            "bank": bank,
            "fuel_prices": 2,
            "promotions": {"ueno": 1},
            "scraper_metrics": {"ueno": {"persisted_promotions_count": 1}},
            "warnings": [],
        },
    )

    client = TestClient(api_main.app)

    collect = client.post("/admin/collect", json={"month": "2026-04", "bank": "ueno"})
    audit = client.post("/admin/audit", json={"month": "2026-04"})

    assert collect.status_code == 200
    assert collect.json()["status"] == "ok"
    assert collect.json()["bank"] == "ueno"
    assert audit.status_code == 200
    assert "dataset" in audit.json()


def test_api_respects_database_url_from_env(monkeypatch, tmp_path: Path) -> None:
    db_url = f"sqlite:///{(tmp_path / 'online.sqlite').as_posix()}"
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("ENABLE_ADMIN_ENDPOINTS", "false")
    reset_settings_cache()

    import api.main as api_main

    api_main = importlib.reload(api_main)
    client = TestClient(api_main.create_app())

    health = client.get("/health")
    admin = client.post("/admin/collect", json={"month": "2026-04"})

    assert health.status_code == 200
    assert health.json()["database_backend"] == "sqlite"
    assert admin.status_code == 403
