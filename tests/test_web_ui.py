from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from models.promotion import FuelPrice, Promotion
from query.repository import PromotionRepository


def _seed_repository(path: Path) -> PromotionRepository:
    repository = PromotionRepository(path)
    repository.save_promotions(
        [
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
            ),
        ]
    )
    repository.save_fuel_prices(
        [
            FuelPrice(
                brand="Copetrol",
                octane=95,
                base_price=7240,
                captured_at="2026-04-17T00:00:00+00:00",
                source_url="https://www.combustibles.com.py/",
            ),
            FuelPrice(
                brand="Copetrol",
                octane=97,
                base_price=10650,
                captured_at="2026-04-17T00:00:00+00:00",
                source_url="https://www.combustibles.com.py/",
            ),
        ]
    )
    return repository


def _build_client(monkeypatch, tmp_path: Path) -> TestClient:
    repository = _seed_repository(tmp_path / "catalog.sqlite")
    import api.main as api_main

    monkeypatch.setattr(api_main, "get_repository", lambda: repository)
    app = api_main.create_app()
    return TestClient(app)


def test_web_home_renders_search_examples_and_recent_queries(monkeypatch, tmp_path: Path) -> None:
    client = _build_client(monkeypatch, tmp_path)
    client.cookies.set("promo_recent_queries", '["quiero comprar en super"]')

    response = client.get("/")

    assert response.status_code == 200
    assert "Promo Query Paraguay" in response.text
    assert "quiero comprar en super" in response.text
    assert "Últimas búsquedas" in response.text
    assert 'name="viewport"' in response.text


def test_web_search_renders_results_and_sets_recent_cookie(monkeypatch, tmp_path: Path) -> None:
    client = _build_client(monkeypatch, tmp_path)

    response = client.get("/search", params={"q": "que tarjeta me conviene para 97"})

    assert response.status_code == 200
    assert "Copetrol" in response.text
    assert "Final estimado" in response.text
    assert "set-cookie" in response.headers


def test_web_search_distinguishes_filter_empty_state(monkeypatch, tmp_path: Path) -> None:
    client = _build_client(monkeypatch, tmp_path)

    response = client.get("/search", params={"q": "quiero comprar en super", "bank": "Continental"})

    assert response.status_code == 200
    assert "Tus filtros dejaron la búsqueda sin resultados visibles" in response.text


def test_web_audit_form_and_invalid_month(monkeypatch, tmp_path: Path) -> None:
    client = _build_client(monkeypatch, tmp_path)

    response = client.post("/audit-ui", data={"month": "2026-13", "bank": "", "query": ""})

    assert response.status_code == 200
    assert "Mes inválido" in response.text


def test_web_fuel_view_filters_by_octane(monkeypatch, tmp_path: Path) -> None:
    client = _build_client(monkeypatch, tmp_path)

    fuel = client.get("/fuel", params={"month": "2026-04", "octane": "95"})

    assert fuel.status_code == 200
    assert "Recomendación 95" in fuel.text
    assert 'class="active">95<' in fuel.text
    assert "Precios agrupados por marca" in fuel.text


def test_web_promotions_view_supports_filters_and_pagination(monkeypatch, tmp_path: Path) -> None:
    client = _build_client(monkeypatch, tmp_path)

    promotions = client.get(
        "/promotions-ui",
        params={"month": "2026-04", "category": "supermercados", "bank": "BNF"},
    )

    assert promotions.status_code == 200
    assert "Vale Stock" in promotions.text
    assert "Página 1 de 1" in promotions.text


def test_web_ops_collect_and_audit_forms(monkeypatch, tmp_path: Path) -> None:
    client = _build_client(monkeypatch, tmp_path)
    import web.routes as web_routes
    import api.main as api_main

    monkeypatch.setattr(
        web_routes,
        "now_month_ref",
        lambda: "2026-04",
    )
    monkeypatch.setattr(
        api_main,
        "start_collect_job",
        lambda background_tasks, month, bank=None: {"status": "started", "month": month, "bank": bank},
    )
    monkeypatch.setattr(
        api_main,
        "get_collect_job_status",
        lambda: {
            "status": "running",
            "started_at": "2026-04-20T12:00:00+00:00",
            "finished_at": None,
            "last_error": None,
            "last_result": None,
            "month": "2026-04",
            "bank": "Ueno",
            "progress": 40,
            "current_step": "Procesando Ueno",
            "current_bank": "ueno",
            "total_steps": 4,
            "completed_steps": 2,
        },
    )
    monkeypatch.setattr(api_main, "get_repository", lambda: _seed_repository(tmp_path / "catalog-second.sqlite"))
    client = TestClient(api_main.create_app())

    collect = client.post("/ops/collect", data={"month": "2026-04", "bank": "Ueno"})
    audit = client.post("/ops/audit", data={"month": "2026-04", "bank": "", "query": "que tarjeta me conviene para 95"})

    assert collect.status_code == 200
    assert "Collect iniciado" in collect.text
    assert "running" in collect.text
    assert "Procesando Ueno" in collect.text
    assert "collect-progress-fill" in collect.text
    assert audit.status_code == 200
    assert "Readiness" in audit.text


def test_web_ops_shows_collect_error_and_last_result(monkeypatch, tmp_path: Path) -> None:
    _build_client(monkeypatch, tmp_path)
    import api.main as api_main

    monkeypatch.setattr(
        api_main,
        "get_collect_job_status",
        lambda: {
            "status": "error",
            "started_at": "2026-04-20T12:00:00+00:00",
            "finished_at": "2026-04-20T12:05:00+00:00",
            "last_error": "collect failed in background",
            "last_result": {
                "month": "2026-04",
                "fuel_prices": 8,
                "promotions_total": 55,
                "banks_processed": ["ueno"],
                "bank_diagnostics": {"ueno": "ok"},
            },
            "month": "2026-04",
            "bank": "itau",
            "progress": 60,
            "current_step": "Collect con error",
            "current_bank": "itau",
            "total_steps": 4,
            "completed_steps": 2,
        },
    )
    client = TestClient(api_main.create_app())
    response = client.get("/ops")

    assert response.status_code == 200
    assert "collect failed in background" in response.text
    assert "promotions_total" in response.text
    assert "ueno" in response.text
    assert "ok" in response.text


def test_web_ops_handles_invalid_input(monkeypatch, tmp_path: Path) -> None:
    client = _build_client(monkeypatch, tmp_path)

    response = client.post("/ops/collect", data={"month": "2026-99", "bank": "Ueno"})

    assert response.status_code == 400
    assert "Mes inválido" in response.text


def test_web_styles_include_mobile_breakpoints() -> None:
    css_path = Path("D:/Bank-scrapper/src/web/static/styles.css")
    css = css_path.read_text(encoding="utf-8")

    assert "@media (max-width: 900px)" in css
    assert "@media (max-width: 640px)" in css
