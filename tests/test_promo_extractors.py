from pathlib import Path

from utils.promo_extractors import (
    extract_cap_amount,
    extract_cashback_percent,
    extract_date_range,
    extract_discount_percent,
    extract_installments,
    extract_minimum_purchase,
    extract_valid_days,
    is_disclaimerish_text,
    split_promo_blocks,
)


def test_extractors_cover_edge_cases() -> None:
    text = Path("tests/fixtures/promo_text_edge_cases.txt").read_text(encoding="utf-8")
    blocks = split_promo_blocks(text)

    assert extract_discount_percent(blocks[0]) == 25.0
    assert extract_cap_amount(blocks[0]) == 120000.0
    assert extract_minimum_purchase(blocks[0]) == 200000.0
    assert extract_valid_days(blocks[0]) == ["friday"]
    start_a, end_a = extract_date_range(blocks[0], fallback_year=2026)
    assert start_a.isoformat() == "2026-04-01"
    assert end_a.isoformat() == "2026-04-30"

    assert extract_cashback_percent(blocks[1]) == 15.0
    assert extract_installments(blocks[1]) == 6
    assert extract_valid_days(blocks[1]) == ["saturday", "sunday"]

    assert extract_cashback_percent(blocks[2]) == 20.0
    start_b, end_b = extract_date_range(blocks[2], fallback_year=2026)
    assert start_b.isoformat() == "2026-04-10"
    assert end_b.isoformat() == "2026-04-20"


def test_extractors_handle_bnf_like_wording() -> None:
    text = Path("tests/fixtures/bnf_edge_case.txt").read_text(encoding="utf-8")

    start_date, end_date = extract_date_range(text, fallback_year=2026)
    assert start_date.isoformat() == "2026-04-05"
    assert end_date.isoformat() == "2026-04-30"
    assert extract_cap_amount(text) == 150000.0
    assert extract_minimum_purchase(text) == 200000.0
    assert extract_valid_days(text) == ["friday", "saturday"]


def test_is_disclaimerish_text_detects_navigation_or_legal_copy() -> None:
    assert is_disclaimerish_text("Ver bases y condiciones en la web.")
    assert is_disclaimerish_text("No aplica para delivery ni giftcard.")
    assert not is_disclaimerish_text("15% de reintegro en Copetrol.")
