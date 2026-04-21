import json
from datetime import date
from pathlib import Path

from typer.testing import CliRunner

import app as app_module
from app import cli
from models.promotion import FuelPrice, Promotion
from query.audit import build_audit_report, render_audit_report
from query.repository import PromotionRepository


def test_audit_report_summarizes_dataset_metrics(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")
    repository.save_promotions(
        [
            Promotion(
                bank="Sudameris",
                title="Promo Copetrol",
                category="combustible",
                merchant="Copetrol",
                merchant_raw="Copetrol SA",
                merchant_normalized="Copetrol",
                brand_normalized="Copetrol",
                cashback_percent=20,
                month_ref="2026-04",
                source_type="html_detail",
                source_url="https://example.com/copetrol",
                raw_text="20% reintegro en Copetrol",
                confidence_score=0.9,
            ),
            Promotion(
                bank="Continental",
                title="Viernes de combustible",
                category="combustible",
                merchant=None,
                merchant_raw=None,
                merchant_normalized=None,
                brand_normalized=None,
                discount_percent=25,
                month_ref="2026-04",
                source_type="html_detail",
                source_url="https://example.com/combustible",
                raw_text="Viernes hasta 25% en combustible",
                confidence_score=0.5,
            ),
            Promotion(
                bank="BNF",
                title="Vale Superseis",
                category="supermercados",
                merchant="Superseis",
                merchant_raw="Superseis",
                merchant_normalized="Superseis",
                brand_normalized="Superseis",
                benefit_type="voucher",
                promo_mechanic="voucher",
                payment_method="puntos",
                month_ref="2026-04",
                source_type="html_detail",
                source_url="https://example.com/voucher",
                raw_text="Solo puntos vale superseis",
                confidence_score=0.4,
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
            ),
            FuelPrice(
                brand="Shell",
                octane=95,
                base_price=8200,
                captured_at="2026-04-17T00:00:00+00:00",
                source_url="https://www.combustibles.com.py/",
            ),
        ]
    )

    report = build_audit_report(repository, month_ref="2026-04", queries=["quiero comprar en super"])

    assert report.dataset.total_promotions == 3
    assert report.dataset.promotions_by_bank["Sudameris"] == 1
    assert report.dataset.promotions_by_bank["Continental"] == 1
    assert report.dataset.promotions_by_bank["BNF"] == 1
    assert report.api_readiness == "warning"
    assert report.dataset.merchant_clear_count == 2
    assert report.dataset.category_only_count == 1
    assert report.dataset.promotions_by_bank_category["Sudameris"]["combustible"] == 1
    assert report.dataset.canonical_offers_total >= 1
    assert report.dataset.featured_candidate_count >= 1
    assert "combustible" in report.dataset.covered_categories
    assert report.dataset.promo_type_distribution["bank_promo"] == 1
    assert report.dataset.promo_type_distribution["generic_benefit"] == 1
    assert report.dataset.promo_type_distribution["voucher"] == 1
    assert report.dataset.fuel.by_octane == {"95": 1, "97": 1}
    assert report.smoke_queries[0].query == "quiero comprar en super"


def test_audit_report_warns_when_dataset_is_degraded(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")
    repository.save_promotions(
        [
            Promotion(
                bank="Sudameris",
                title="Beneficios",
                category="combustible",
                merchant=None,
                merchant_raw=None,
                merchant_normalized=None,
                brand_normalized=None,
                discount_percent=20,
                month_ref="2026-04",
                source_type="html_detail",
                source_url="https://example.com/generica",
                raw_text="Beneficios de combustible",
                confidence_score=0.3,
            )
        ]
    )

    report = build_audit_report(
        repository,
        month_ref="2026-04",
        bank="sudameris",
        queries=["que tarjeta me conviene para 97", "hoy necesito comprar clavos", "que banco me conviene hoy"],
    )
    issue_codes = {item.code for item in report.issues}

    assert report.api_readiness == "blocked"
    assert "fuel_prices_empty" in issue_codes
    assert "merchant_quality_degraded" in issue_codes
    assert "fuel_query_without_base_price" in issue_codes
    assert "no_live_promos_for_category" in issue_codes


def test_audit_report_flags_suspicious_normalized_merchants(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")
    repository.save_promotions(
        [
            Promotion(
                bank="Itau",
                title="Conocer promos",
                category="retail",
                merchant="Conocer promos",
                merchant_raw="Conocer promos",
                merchant_normalized="Conocer Promos",
                brand_normalized=None,
                month_ref="2026-04",
                source_type="html_listing",
                source_url="https://example.com/itau",
                raw_text="Conocer promos",
                confidence_score=0.2,
            )
        ]
    )

    report = build_audit_report(repository, month_ref="2026-04", bank="itau", queries=["quiero promociones"])

    assert report.dataset.suspicious_merchant_count == 1
    assert report.dataset.suspicious_merchants["Conocer Promos"] == 1
    assert any(item.code == "suspicious_normalized_merchants" for item in report.issues)


def test_audit_report_does_not_flag_suspicious_when_cta_is_not_normalized(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")
    repository.save_promotions(
        [
            Promotion(
                bank="Ueno",
                title="Conocer promos",
                category="retail",
                merchant=None,
                merchant_raw=None,
                merchant_normalized=None,
                brand_normalized=None,
                month_ref="2026-04",
                source_type="html_listing",
                source_url="https://example.com/ueno",
                raw_text="Conocer promos",
                confidence_score=0.1,
            )
        ]
    )

    report = build_audit_report(repository, month_ref="2026-04", bank="ueno", queries=["quiero promociones"])

    assert report.dataset.suspicious_merchant_count == 0
    assert all(item.code != "suspicious_normalized_merchants" for item in report.issues)


def test_audit_report_ready_when_core_signals_are_healthy(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")
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
                bank="Itau",
                title="Promo Superseis",
                category="supermercados",
                merchant="Superseis",
                merchant_raw="Superseis",
                merchant_normalized="Superseis",
                brand_normalized="Superseis",
                cashback_percent=15,
                month_ref="2026-04",
                source_type="html_detail",
                source_url="https://example.com/itau/superseis",
                raw_text="15% de reintegro en Superseis",
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
                month_ref="2026-04",
                source_type="html_detail",
                source_url="https://example.com/sudameris/copetrol",
                raw_text="25% de reintegro en Copetrol",
                confidence_score=0.9,
            ),
            Promotion(
                bank="Continental",
                title="Promo Shell",
                category="combustible",
                merchant="Shell",
                merchant_raw="Shell",
                merchant_normalized="Shell",
                brand_normalized="Shell",
                discount_percent=20,
                month_ref="2026-04",
                source_type="html_detail",
                source_url="https://example.com/continental/shell",
                raw_text="20% de descuento en Shell",
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
                promo_mechanic="voucher",
                payment_method="puntos",
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
                octane=97,
                base_price=10000,
                captured_at="2026-04-17T00:00:00+00:00",
                source_url="https://www.combustibles.com.py/",
            )
        ]
    )

    report = build_audit_report(
        repository,
        month_ref="2026-04",
        queries=["que tarjeta me conviene para 97", "quiero comprar en super"],
    )

    assert report.api_readiness == "ready"
    assert report.api_readiness_reasons == []


def test_render_audit_report_includes_sections_and_matches(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")
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
                source_url="https://example.com/copetrol",
                raw_text="25% reintegro en Copetrol",
                confidence_score=0.9,
            )
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

    report = build_audit_report(repository, month_ref="2026-04", queries=["que tarjeta me conviene para 97"])
    rendered = render_audit_report(report)

    assert "== Dataset ==" in rendered
    assert "== Smoke queries ==" in rendered
    assert "== Coverage by category ==" in rendered
    assert "== Canonical offers ==" in rendered
    assert "Copetrol" in rendered
    assert "price_base=10000.0" in rendered


def test_audit_cli_json_output(monkeypatch, tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")
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
                month_ref="2026-04",
                source_type="html_detail",
                source_url="https://example.com/copetrol",
                raw_text="25% reintegro en Copetrol",
                confidence_score=0.9,
            )
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
    monkeypatch.setattr(app_module.PromotionRepository, "default", classmethod(lambda cls: repository))

    result = CliRunner().invoke(cli, ["audit", "--month", "2026-04", "--json", "--query", "que tarjeta me conviene para 97"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["dataset"]["total_promotions"] == 1
    assert payload["smoke_queries"][0]["query"] == "que tarjeta me conviene para 97"


def test_audit_report_warns_on_old_octane_logic(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")
    repository.save_promotions([])
    repository.save_fuel_prices(
        [
            FuelPrice(
                brand="Shell",
                octane=93,
                base_price=7990,
                captured_at="2026-04-17T00:00:00+00:00",
                source_url="https://www.combustibles.com.py/",
            )
        ]
    )

    report = build_audit_report(repository, month_ref="2026-04", bank="ueno", queries=["que tarjeta me conviene para 95"])
    issue_codes = {item.code for item in report.issues}

    assert "fuel_octane_mismatch" in issue_codes
