from __future__ import annotations

from datetime import date
from pathlib import Path

from models.promotion import Promotion
from offers import build_offer_catalog, build_today_feed
from offers.sources import load_supplemental_offer_sources


def _promo(**overrides):
    payload = {
        "bank": "Sudameris",
        "title": "Promo Biggie",
        "category": "supermercados",
        "merchant": "Biggie",
        "merchant_raw": "Biggie",
        "merchant_normalized": "Biggie",
        "brand_normalized": "Biggie",
        "cashback_percent": 20,
        "month_ref": "2026-04",
        "source_type": "html_detail",
        "source_url": "https://example.com/biggie",
        "raw_text": "20% reintegro en Biggie",
        "confidence_score": 0.9,
    }
    payload.update(overrides)
    return Promotion(**payload)


def test_build_offer_catalog_maps_promotion_to_canonical_offer() -> None:
    offer = build_offer_catalog([_promo()], today=date(2026, 4, 21))[0]

    assert offer.bank == "Sudameris"
    assert offer.merchant_normalized == "Biggie"
    assert offer.category == "supermercados"
    assert offer.benefit_type == "cashback"
    assert offer.benefit_summary == "20% reintegro"
    assert offer.promo_type == "bank_promo"
    assert offer.is_today_relevant is True
    assert offer.is_featured_candidate is True
    assert offer.source_type == "bank_detail_page"


def test_offer_catalog_deduplicates_logical_duplicates() -> None:
    offers = build_offer_catalog(
        [
            _promo(source_type="html_detail", source_url="https://example.com/detail"),
            _promo(source_type="pdf_campaign", source_url="https://example.com/pdf"),
        ]
    )

    assert len(offers) == 1
    assert offers[0].source_count == 2


def test_today_feed_groups_and_prioritizes_offers_by_category() -> None:
    offers = build_offer_catalog(
        [
            _promo(),
            _promo(
                title="Promo Copetrol",
                category="combustible",
                merchant="Copetrol",
                merchant_raw="Copetrol",
                merchant_normalized="Copetrol",
                brand_normalized="Copetrol",
                cashback_percent=25,
                raw_text="25% reintegro en Copetrol",
            ),
            _promo(
                title="Beneficio generico",
                category="retail",
                merchant=None,
                merchant_raw=None,
                merchant_normalized=None,
                brand_normalized=None,
                cashback_percent=None,
                raw_text="Beneficios en comercios seleccionados",
                confidence_score=0.2,
            ),
        ]
    )
    feed = build_today_feed(offers)

    assert feed["total"] >= 2
    assert "supermercados" in feed["grouped"]
    assert "combustible" in feed["grouped"]
    assert feed["featured_offers"][0].merchant_normalized in {"Copetrol", "Biggie"}


def test_offer_catalog_accepts_manual_and_merchant_campaign_sources() -> None:
    offers = build_offer_catalog(
        [],
        supplemental_sources=[
            {
                "source_type": "manual_source",
                "bank": "Banco Demo",
                "merchant": "Super Demo",
                "merchant_normalized": "Super Demo",
                "category": "supermercados",
                "cashback_percent": 15,
                "benefit_summary": "15% reintegro fines de semana",
                "valid_until": "2026-04-30",
                "confidence_score": 0.8,
            },
            {
                "source_type": "merchant_campaign",
                "merchant": "Tienda Demo",
                "merchant_normalized": "Tienda Demo",
                "category": "retail",
                "discount_percent": 20,
                "channels": ["ecommerce"],
                "confidence_score": 0.75,
            },
        ],
        today=date(2026, 4, 21),
    )

    assert {item.source_type for item in offers} == {"manual_source", "merchant_campaign"}
    assert {item.source_family for item in offers} == {"manual", "merchant"}
    assert all(item.promo_type == "bank_promo" for item in offers)
    assert all(item.is_today_relevant for item in offers)


def test_offer_catalog_accepts_social_signal_as_low_confidence_context() -> None:
    offer = build_offer_catalog(
        [],
        supplemental_sources=[
            {
                "source_type": "social_signal",
                "merchant": "Restaurante Demo",
                "merchant_normalized": "Restaurante Demo",
                "category": "gastronomia",
                "benefit_summary": "Senal vista en redes, pendiente de verificar",
                "confidence_score": 0.35,
            }
        ],
    )[0]

    assert offer.source_type == "social_signal"
    assert offer.source_family == "social"
    assert offer.offer_quality_label == "low"


def test_load_supplemental_offer_sources_filters_supported_types(tmp_path: Path) -> None:
    config = tmp_path / "manual_offers.yaml"
    config.write_text(
        """
offers:
  - source_type: manual_source
    merchant: Super Demo
    category: supermercados
  - source_type: unknown_source
    merchant: Ruido
""",
        encoding="utf-8",
    )

    sources = load_supplemental_offer_sources(config)

    assert len(sources) == 1
    assert sources[0]["merchant"] == "Super Demo"
