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

    api_main.reset_collect_job_state()
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


def test_admin_collect_starts_in_background_and_updates_status(monkeypatch, tmp_path: Path) -> None:
    repository = _seed_repository(tmp_path / "catalog.sqlite")
    import api.main as api_main

    api_main.reset_collect_job_state()
    monkeypatch.setattr(api_main, "get_repository", lambda: repository)
    monkeypatch.setattr(api_main, "_ensure_admin_enabled", lambda settings: None)
    monkeypatch.setattr(
        api_main,
        "run_collect",
        lambda repo, month, bank=None, progress_callback=None: {
            "month": month,
            "bank": bank,
            "fuel_prices": 2,
            "promotions": {"ueno": 1},
            "scraper_metrics": {"ueno": {"persisted_promotions_count": 1}},
            "bank_diagnostics": {"ueno": "ok"},
            "warnings": [],
        },
    )
    client = TestClient(api_main.app)

    collect = client.post("/admin/collect", json={"month": "2026-04", "bank": "itau"})
    status = client.get("/admin/collect/status")

    assert collect.status_code == 200
    assert collect.json() == {"status": "started", "month": "2026-04", "bank": "itau"}
    assert status.status_code == 200
    assert status.json()["status"] in {"running", "done"}
    assert status.json()["month"] == "2026-04"
    assert status.json()["bank"] == "itau"
    assert {"progress", "current_step", "current_bank", "total_steps", "completed_steps"} <= set(status.json())
    if status.json()["status"] == "done":
        assert status.json()["finished_at"] is not None
        assert status.json()["progress"] == 100
        assert status.json()["last_result"]["promotions_total"] == 1
        assert status.json()["last_result"]["bank_diagnostics"] == {"ueno": "ok"}


def test_admin_collect_returns_400_when_month_missing(monkeypatch, tmp_path: Path) -> None:
    repository = _seed_repository(tmp_path / "catalog.sqlite")
    import api.main as api_main

    api_main.reset_collect_job_state()
    monkeypatch.setattr(api_main, "get_repository", lambda: repository)
    monkeypatch.setattr(api_main, "_ensure_admin_enabled", lambda settings: None)
    client = TestClient(api_main.app)

    response = client.post("/admin/collect", json={})

    assert response.status_code == 400


def test_admin_collect_returns_400_when_bank_invalid(monkeypatch, tmp_path: Path) -> None:
    repository = _seed_repository(tmp_path / "catalog.sqlite")
    import api.main as api_main

    api_main.reset_collect_job_state()
    monkeypatch.setattr(api_main, "get_repository", lambda: repository)
    monkeypatch.setattr(api_main, "_ensure_admin_enabled", lambda settings: None)
    client = TestClient(api_main.app)

    response = client.post("/admin/collect", json={"month": "2026-04", "bank": "banco-xyz"})

    assert response.status_code == 400


def test_admin_collect_returns_409_when_already_running(monkeypatch, tmp_path: Path) -> None:
    repository = _seed_repository(tmp_path / "catalog.sqlite")
    import api.main as api_main

    api_main.reset_collect_job_state()
    monkeypatch.setattr(api_main, "get_repository", lambda: repository)
    monkeypatch.setattr(api_main, "_ensure_admin_enabled", lambda settings: None)
    api_main._collect_job_state.try_start(month="2026-04", bank="ueno")

    client = TestClient(api_main.app)
    response = client.post("/admin/collect", json={"month": "2026-04", "bank": "itau"})

    assert response.status_code == 409


def test_admin_collect_persists_error_when_background_fails(monkeypatch, tmp_path: Path) -> None:
    repository = _seed_repository(tmp_path / "catalog.sqlite")
    import api.main as api_main

    api_main.reset_collect_job_state()
    monkeypatch.setattr(api_main, "get_repository", lambda: repository)
    monkeypatch.setattr(api_main, "_ensure_admin_enabled", lambda settings: None)

    def _boom(repo, month, bank=None, progress_callback=None):
        raise RuntimeError("collect failed in background")

    monkeypatch.setattr(api_main, "run_collect", _boom)
    client = TestClient(api_main.app)

    collect = client.post("/admin/collect", json={"month": "2026-04"})
    status = client.get("/admin/collect/status")

    assert collect.status_code == 200
    assert status.status_code == 200
    assert status.json()["status"] == "error"
    assert "collect failed in background" in (status.json()["last_error"] or "")
    assert status.json()["finished_at"] is not None
    assert status.json()["current_step"] == "Collect con error"


def test_admin_collect_success_after_previous_error(monkeypatch, tmp_path: Path) -> None:
    repository = _seed_repository(tmp_path / "catalog.sqlite")
    import api.main as api_main

    api_main.reset_collect_job_state()
    monkeypatch.setattr(api_main, "get_repository", lambda: repository)
    monkeypatch.setattr(api_main, "_ensure_admin_enabled", lambda settings: None)
    client = TestClient(api_main.app)

    def _boom(repo, month, bank=None, progress_callback=None):
        raise RuntimeError("first collect failed")

    monkeypatch.setattr(api_main, "run_collect", _boom)
    fail = client.post("/admin/collect", json={"month": "2026-04"})
    assert fail.status_code == 200
    failed_status = client.get("/admin/collect/status").json()
    assert failed_status["status"] == "error"

    monkeypatch.setattr(
        api_main,
        "run_collect",
        lambda repo, month, bank=None, progress_callback=None: {
            "month": month,
            "bank": bank,
            "fuel_prices": 1,
            "promotions": 2,
            "warnings": [],
        },
    )
    ok = client.post("/admin/collect", json={"month": "2026-04", "bank": "ueno"})
    done_status = client.get("/admin/collect/status").json()

    assert ok.status_code == 200
    assert done_status["status"] == "done"
    assert done_status["last_error"] is None
    assert done_status["finished_at"] is not None
    assert done_status["last_result"]["promotions_total"] == 2
    assert "bank_diagnostics" in done_status["last_result"]


def test_collect_job_progress_updates_for_general_collect(monkeypatch, tmp_path: Path) -> None:
    repository = _seed_repository(tmp_path / "catalog.sqlite")
    import api.main as api_main

    api_main.reset_collect_job_state()
    monkeypatch.setattr(api_main, "get_repository", lambda: repository)
    monkeypatch.setattr(api_main, "_ensure_admin_enabled", lambda settings: None)

    def _collect(repo, month, bank=None, progress_callback=None):
        assert progress_callback is not None
        progress_callback({"current_step": "Procesando Ueno", "current_bank": "ueno", "completed_steps": 2})
        snapshot = api_main.get_collect_job_status()
        assert snapshot["status"] == "running"
        assert snapshot["progress"] > 0
        assert snapshot["current_bank"] == "ueno"
        return {
            "month": month,
            "bank": bank,
            "fuel_prices": 8,
            "promotions": {"ueno": 14, "itau": 22},
            "bank_diagnostics": {"ueno": "ok", "itau": "ok"},
            "warnings": [],
        }

    monkeypatch.setattr(api_main, "run_collect", _collect)
    client = TestClient(api_main.app)

    response = client.post("/admin/collect", json={"month": "2026-04"})
    status = client.get("/admin/collect/status").json()

    assert response.status_code == 200
    assert status["status"] == "done"
    assert status["progress"] == 100
    assert status["last_result"]["banks_processed"] == ["itau", "ueno"]


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
