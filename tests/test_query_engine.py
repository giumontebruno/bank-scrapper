from datetime import date
from pathlib import Path

from catalog.service import CatalogService
from models.promotion import FuelPrice, Promotion
from query.engine import QueryEngine
from query.ranking import PROMO_TYPE_PRIORITY, infer_promo_type, result_quality
from query.repository import PromotionRepository

QUALITY_ORDER = {"fallback": 0, "low": 1, "medium": 2, "high": 3}


def test_query_engine_matches_hardware_need(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")
    repository.save_promotions(
        [
            Promotion(
                bank="Sudameris",
                title="Promo Ferrex",
                category="ferreteria",
                merchant="Ferrex",
                merchant_raw="Ferrex",
                merchant_normalized="Ferrex",
                brand_normalized="Ferrex",
                discount_percent=20,
                benefit_type="discount",
                end_date=date(2026, 4, 30),
                source_type="html_detail",
                source_url="https://example.com/ferrex",
                raw_text="20% de descuento en Ferrex",
                confidence_score=0.9,
            )
        ]
    )

    response = QueryEngine(repository).query("hoy necesito comprar clavos")

    assert response["query"] == "hoy necesito comprar clavos"
    assert len(response["matches"]) == 1
    assert response["matches"][0]["merchant"] == "Ferrex"
    assert response["matches"][0]["benefit"] == "20% desc."
    assert response["matches"][0]["result_quality_label"] in {"medium", "high"}


def test_query_engine_ranks_fuel_by_final_price(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")
    repository.save_promotions(
        [
            Promotion(
                bank="Itau",
                title="Shell 97",
                category="combustible",
                merchant="Shell Mcal Lopez",
                merchant_raw="Shell Mcal Lopez",
                merchant_normalized="Shell",
                brand_normalized="Shell",
                discount_percent=10,
                benefit_type="discount",
                end_date=date(2026, 4, 30),
                source_type="html_listing",
                source_url="https://example.com/shell",
                raw_text="10% Shell 97",
                confidence_score=0.9,
            ),
            Promotion(
                bank="Continental",
                title="Copetrol 97",
                category="combustible",
                merchant="Copetrol SA Acceso Sur",
                merchant_raw="Copetrol SA Acceso Sur",
                merchant_normalized="Copetrol",
                brand_normalized="Copetrol",
                cashback_percent=15,
                benefit_type="cashback",
                end_date=date(2026, 4, 30),
                source_type="html_listing",
                source_url="https://example.com/copetrol",
                raw_text="15% Copetrol 97",
                confidence_score=0.9,
            ),
        ]
    )
    repository.save_fuel_prices(
        [
            FuelPrice(
                brand="Shell",
                octane=97,
                base_price=8540,
                captured_at="2026-04-16T00:00:00+00:00",
                source_url="https://www.combustibles.com.py/",
            ),
            FuelPrice(
                brand="Copetrol",
                octane=97,
                base_price=8290,
                captured_at="2026-04-16T00:00:00+00:00",
                source_url="https://www.combustibles.com.py/",
            ),
        ]
    )

    response = QueryEngine(repository).query("que tarjeta me conviene para 97")

    assert len(response["matches"]) == 2
    assert response["matches"][0]["merchant"] == "Copetrol"
    assert response["matches"][0]["price_final_estimated"] == 7046.5
    assert response["matches"][0]["result_quality_label"] == "high"
    assert "Final estimado" in response["matches"][0]["explanation"]


def test_query_engine_returns_base_price_when_no_promotion_exists(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")
    repository.save_fuel_prices(
        [
            FuelPrice(
                brand="Shell",
                octane=95,
                base_price=7990,
                captured_at="2026-04-16T00:00:00+00:00",
                source_url="https://www.combustibles.com.py/",
            )
        ]
    )

    response = QueryEngine(repository).query("me conviene cargar 95 hoy")

    assert len(response["matches"]) == 1
    assert response["matches"][0]["bank"] is None
    assert response["matches"][0]["price_final_estimated"] == 7990
    assert response["matches"][0]["benefit"] == "sin promoción detectada"
    assert response["matches"][0]["promo_type"] == "generic_benefit"


def test_query_engine_joins_brand_normalized_fuel_prices(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")
    repository.save_promotions(
        [
            Promotion(
                bank="Sudameris",
                title="Copetrol Acceso Sur",
                category="combustible",
                merchant="Copetrol SA Acceso Sur",
                merchant_raw="Copetrol SA Acceso Sur",
                merchant_normalized="Copetrol",
                brand_normalized="Copetrol",
                cashback_percent=20,
                end_date=date(2026, 4, 30),
                source_type="html_detail",
                source_url="https://example.com/copetrol",
                raw_text="20% de reintegro en Copetrol Acceso Sur",
                confidence_score=0.9,
            )
        ]
    )
    repository.save_fuel_prices(
        [
            FuelPrice(
                brand="Copetrol",
                octane=97,
                base_price=8290,
                captured_at="2026-04-16T00:00:00+00:00",
                source_url="https://www.combustibles.com.py/",
            )
        ]
    )

    response = QueryEngine(repository).query("que tarjeta me conviene para 97")

    assert response["matches"][0]["merchant"] == "Copetrol"
    assert response["matches"][0]["price_base"] == 8290
    assert response["matches"][0]["price_final_estimated"] == 6632.0


def test_query_engine_keeps_promo_without_price(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")
    repository.save_promotions(
        [
            Promotion(
                bank="Sudameris",
                title="Promo Superseis",
                category="supermercados",
                merchant="Super 6",
                merchant_raw="Super 6",
                merchant_normalized="Superseis",
                brand_normalized="Superseis",
                cashback_percent=15,
                cap_amount=120000,
                valid_days=["saturday"],
                end_date=date(2026, 4, 30),
                source_type="pdf_campaign",
                source_url="https://example.com/superseis",
                raw_text="15% de reintegro en Super 6 los sabados",
                confidence_score=0.8,
            )
        ]
    )

    response = QueryEngine(repository).query("quiero comprar en super")

    assert len(response["matches"]) == 1
    assert response["matches"][0]["merchant"] == "Superseis"
    assert response["matches"][0]["price_base"] is None
    assert response["matches"][0]["price_final_estimated"] is None
    assert response["matches"][0]["ranking_score"] is not None
    assert response["matches"][0]["promo_type"] == "bank_promo"


def test_query_engine_ranks_promo_above_plain_price_when_both_exist(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")
    repository.save_promotions(
        [
            Promotion(
                bank="Continental",
                title="Shell 97",
                category="combustible",
                merchant="Shell Palma",
                merchant_raw="Shell Palma",
                merchant_normalized="Shell",
                brand_normalized="Shell",
                discount_percent=10,
                end_date=date(2026, 4, 30),
                source_type="html_detail",
                source_url="https://example.com/shell",
                raw_text="10% Shell",
                confidence_score=0.9,
            )
        ]
    )
    repository.save_fuel_prices(
        [
            FuelPrice(
                brand="Shell",
                octane=97,
                base_price=8500,
                captured_at="2026-04-16T00:00:00+00:00",
                source_url="https://www.combustibles.com.py/",
            ),
            FuelPrice(
                brand="Petrobras",
                octane=97,
                base_price=8300,
                captured_at="2026-04-16T00:00:00+00:00",
                source_url="https://www.combustibles.com.py/",
            ),
        ]
    )

    response = QueryEngine(repository).query("que tarjeta me conviene para 97")

    assert response["matches"][0]["bank"] == "Continental"
    assert response["matches"][0]["price_final_estimated"] == 7650.0
    assert any(item["bank"] is None for item in response["matches"])


def test_query_engine_expands_generic_fuel_promos_across_prices(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")
    repository.save_promotions(
        [
            Promotion(
                bank="Continental",
                title="Viernes de combustible",
                category="combustible",
                merchant=None,
                merchant_raw=None,
                merchant_normalized=None,
                brand_normalized=None,
                discount_percent=25,
                valid_days=["friday"],
                end_date=date(2026, 4, 30),
                source_type="html_detail",
                source_url="https://example.com/calendario",
                raw_text="Viernes: hasta 25% en combustible",
                confidence_score=0.8,
            )
        ]
    )
    repository.save_fuel_prices(
        [
            FuelPrice(
                brand="Shell",
                octane=97,
                base_price=10000,
                captured_at="2026-04-16T00:00:00+00:00",
                source_url="https://www.combustibles.com.py/",
            ),
            FuelPrice(
                brand="Copetrol",
                octane=97,
                base_price=9800,
                captured_at="2026-04-16T00:00:00+00:00",
                source_url="https://www.combustibles.com.py/",
            ),
        ]
    )

    response = QueryEngine(repository).query("que tarjeta me conviene para 97")

    assert len(response["matches"]) == 2
    assert response["matches"][0]["merchant"] == "Copetrol"
    assert response["matches"][0]["price_final_estimated"] == 7350.0
    assert all(item["bank"] == "Continental" for item in response["matches"])
    assert all(item["promo_type"] == "generic_benefit" for item in response["matches"])


def test_query_engine_supports_octane_95_queries(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")
    repository.save_promotions(
        [
            Promotion(
                bank="Sudameris",
                title="Promo Shell 95",
                category="combustible",
                merchant="Shell",
                merchant_raw="Shell",
                merchant_normalized="Shell",
                brand_normalized="Shell",
                cashback_percent=20,
                source_type="html_detail",
                source_url="https://example.com/shell95",
                raw_text="20% de reintegro en Shell para combustible 95",
                confidence_score=0.8,
            )
        ]
    )
    repository.save_fuel_prices(
        [
            FuelPrice(
                brand="Shell",
                octane=95,
                base_price=7240,
                captured_at="2026-04-16T00:00:00+00:00",
                source_url="https://www.combustibles.com.py/",
            )
        ]
    )

    response = QueryEngine(repository).query("que tarjeta me conviene para 95")

    assert response["matches"]
    assert response["matches"][0]["merchant"] == "Shell"
    assert response["matches"][0]["price_base"] == 7240
    assert response["matches"][0]["price_final_estimated"] == 5792.0


def test_query_engine_returns_bnf_supermarket_vouchers_as_promo_only(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")
    repository.save_promotions(
        [
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
                channel="app",
                source_type="html_detail",
                source_url="https://bnficios.bnf.gov.py/producto/747/vale-de-compra-superseis-100-000-gs",
                raw_text="SOLO PUNTOS vale para compra Superseis",
                confidence_score=0.45,
            )
        ]
    )

    response = QueryEngine(repository).query("quiero comprar en super")

    assert len(response["matches"]) == 1
    assert response["matches"][0]["bank"] == "BNF"
    assert response["matches"][0]["benefit"] == "voucher"
    assert response["matches"][0]["promo_type"] == "voucher"
    assert response["matches"][0]["result_quality_label"] in {"low", "fallback"}


def test_query_engine_falls_back_to_catalog_when_no_promo_exists(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")

    response = QueryEngine(repository).query("hoy necesito comprar clavos")

    assert response["matches"]
    assert response["matches"][0]["merchant"] == "Ferrex"
    assert response["matches"][0]["bank"] is None
    assert response["matches"][0]["benefit"] == "sin promoción detectada"
    assert response["matches"][0]["promo_type"] == "catalog_fallback"
    assert response["matches"][0]["result_quality_label"] == "fallback"


def test_query_engine_maps_material_terms_to_ferreteria_fallback(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")

    response = QueryEngine(repository).query("necesito tornillos y materiales")

    assert response["matches"]
    assert response["matches"][0]["merchant"] == "Ferrex"
    assert response["matches"][0]["promo_type"] == "catalog_fallback"


def test_query_engine_matches_indumentaria_queries_without_fuel_bias(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")
    repository.save_promotions(
        [
            Promotion(
                bank="Ueno",
                title="Promo Koala",
                category="indumentaria",
                merchant="Koala",
                merchant_raw="Koala",
                merchant_normalized="Koala",
                cashback_percent=20,
                source_type="html_detail",
                source_url="https://example.com/koala",
                raw_text="20% de reintegro en Koala",
                confidence_score=0.8,
            )
        ]
    )

    response = QueryEngine(repository).query("quiero ver promos de ropa")

    assert response["matches"]
    assert response["matches"][0]["merchant"] == "Koala"
    assert response["matches"][0]["category"] == "indumentaria"


def test_query_engine_matches_tecnologia_queries(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")
    repository.save_promotions(
        [
            Promotion(
                bank="Sudameris",
                title="Promo Opentech",
                category="tecnologia",
                merchant="Opentech",
                merchant_raw="Opentech",
                merchant_normalized="Opentech",
                installments=12,
                source_type="html_detail",
                source_url="https://example.com/opentech",
                raw_text="Hasta 12 cuotas en Opentech",
                confidence_score=0.8,
            )
        ]
    )

    response = QueryEngine(repository).query("quiero comprar tecnologia")

    assert response["matches"]
    assert response["matches"][0]["merchant"] == "Opentech"
    assert response["matches"][0]["category"] == "tecnologia"


def test_query_engine_matches_gastronomia_queries(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")
    repository.save_promotions(
        [
            Promotion(
                bank="Continental",
                title="Promo restaurante",
                category="gastronomia",
                merchant="Della Poletti",
                merchant_raw="Della Poletti",
                merchant_normalized="Della Poletti",
                discount_percent=15,
                source_type="html_detail",
                source_url="https://example.com/della-poletti",
                raw_text="15% de descuento para salir a comer en Della Poletti",
                confidence_score=0.7,
            )
        ]
    )

    response = QueryEngine(repository).query("quiero salir a comer")

    assert response["matches"]
    assert response["matches"][0]["category"] == "gastronomia"
    assert response["matches"][0]["merchant"] == "Della Poletti"


def test_query_engine_matches_salud_queries_from_text_when_category_is_missing(tmp_path: Path) -> None:
    repository = PromotionRepository(tmp_path / "catalog.sqlite")
    repository.save_promotions(
        [
            Promotion(
                bank="Sudameris",
                title="BIGGIE FARMA",
                category=None,
                merchant="Biggie",
                merchant_raw="Biggie",
                merchant_normalized="Biggie",
                discount_percent=20,
                cashback_percent=10,
                source_type="html_detail",
                source_url="https://example.com/biggie-farma",
                raw_text="BIGGIE FARMA 20% de descuento en caja y 10% de reintegro",
                confidence_score=0.8,
            )
        ]
    )

    response = QueryEngine(repository).query("quiero comprar en farmacia")

    assert response["matches"]
    assert response["matches"][0]["category"] == "salud"


def test_quality_score_prefers_clear_bank_promo_over_generic_benefit() -> None:
    clear = Promotion(
        bank="Sudameris",
        title="Promo Copetrol",
        category="combustible",
        merchant="Copetrol",
        merchant_raw="Copetrol SA",
        merchant_normalized="Copetrol",
        brand_normalized="Copetrol",
        cashback_percent=25,
        channel="presencial",
        end_date=date(2026, 4, 30),
        source_type="html_detail",
        source_url="https://example.com/copetrol",
        raw_text="25% reintegro en Copetrol",
        confidence_score=0.9,
    )
    generic = Promotion(
        bank="Continental",
        title="Viernes hasta 25 en combustible",
        category="combustible",
        discount_percent=25,
        source_type="html_detail",
        source_url="https://example.com/generica",
        raw_text="Viernes hasta 25 en combustible",
        confidence_score=0.5,
    )

    clear_type = infer_promo_type(clear)
    generic_type = infer_promo_type(generic)
    clear_score, clear_label = result_quality(clear, None, promo_type=clear_type)
    generic_score, generic_label = result_quality(generic, None, promo_type=generic_type)

    assert clear_type == "bank_promo"
    assert generic_type == "generic_benefit"
    assert clear_score > generic_score
    assert QUALITY_ORDER[clear_label] >= QUALITY_ORDER[generic_label]


def test_cleaner_null_merchant_pushes_generic_result_below_clear_merchant(tmp_path: Path) -> None:
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
                source_type="html_detail",
                source_url="https://example.com/copetrol",
                raw_text="25% reintegro en Copetrol",
                confidence_score=0.9,
            ),
            Promotion(
                bank="Continental",
                title="Viernes hasta 25 en combustible",
                category="combustible",
                merchant=None,
                merchant_raw=None,
                merchant_normalized=None,
                brand_normalized=None,
                discount_percent=25,
                source_type="html_detail",
                source_url="https://example.com/generica",
                raw_text="Viernes hasta 25 en combustible",
                confidence_score=0.5,
            ),
        ]
    )

    response = QueryEngine(repository).query("quiero promociones")

    assert response["matches"][0]["merchant"] == "Copetrol"
    assert response["matches"][0]["promo_type"] == "bank_promo"
    assert any(item["promo_type"] == "generic_benefit" for item in response["matches"])


def test_broad_query_prioritizes_actionable_results_over_voucher_and_generic(tmp_path: Path) -> None:
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
                source_type="html_detail",
                source_url="https://example.com/copetrol",
                raw_text="25% reintegro en Copetrol",
                confidence_score=0.9,
            ),
            Promotion(
                bank="Continental",
                title="Viernes hasta 25 en combustible",
                category="combustible",
                discount_percent=25,
                source_type="html_detail",
                source_url="https://example.com/generica",
                raw_text="Viernes hasta 25 en combustible",
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
                source_type="html_detail",
                source_url="https://example.com/voucher",
                raw_text="Solo puntos vale superseis",
                confidence_score=0.3,
            ),
        ]
    )
    repository.save_fuel_prices(
        [
            FuelPrice(
                brand="Copetrol",
                octane=97,
                base_price=10000,
                captured_at="2026-04-16T00:00:00+00:00",
                source_url="https://www.combustibles.com.py/",
            )
        ]
    )

    response = QueryEngine(repository).query("que banco me conviene hoy")

    assert response["matches"][0]["merchant"] == "Copetrol"
    assert response["matches"][0]["promo_type"] == "bank_promo"
    assert response["matches"][0]["result_quality_label"] in {"high", "medium"}


def test_catalog_covers_weak_category_terms() -> None:
    catalog = CatalogService()

    assert catalog.infer_category("quiero comprar tecnologia y celulares") == "tecnologia"
    assert catalog.infer_category("busco eventos o teatro") == "entretenimiento"
    assert catalog.infer_category("necesito repuestos y tornillos") == "ferreteria"


def test_ranking_keeps_bank_promos_above_generic_benefits() -> None:
    assert PROMO_TYPE_PRIORITY["bank_promo"] > PROMO_TYPE_PRIORITY["generic_benefit"]
    assert PROMO_TYPE_PRIORITY["generic_benefit"] > PROMO_TYPE_PRIORITY["catalog_fallback"]
