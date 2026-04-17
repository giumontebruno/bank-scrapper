from pathlib import Path

from scrapers.fuel_prices import parse_fuel_prices_from_html, parse_fuel_prices_from_text


def test_parse_fuel_prices_only_95_and_97() -> None:
    html = Path("tests/fixtures/fuel_prices_sample.html").read_text(encoding="utf-8")
    prices = parse_fuel_prices_from_html(html, "https://www.combustibles.com.py/")

    assert {(item.brand, item.octane) for item in prices} == {
        ("Shell", 97),
        ("Shell", 95),
        ("Petropar", 95),
        ("Copetrol", 97),
    }
    assert all(item.octane in {95, 97} for item in prices)
    assert all(item.base_price >= 7000 for item in prices)


def test_parse_fuel_prices_from_current_like_sections() -> None:
    html = Path("tests/fixtures/fuel_prices_current_like.html").read_text(encoding="utf-8")

    prices = parse_fuel_prices_from_html(html, "https://www.combustibles.com.py/")

    assert {(item.brand, item.octane) for item in prices} == {
        ("Shell", 95),
        ("Copetrol", 95),
        ("Petropar", 95),
        ("Shell", 97),
        ("Petrobras", 97),
        ("Enex", 97),
    }
    assert all("Diesel" not in (item.raw_text or "") for item in prices)


def test_parse_fuel_prices_from_text_ignores_other_grades() -> None:
    text = """
    Nafta Intermedia
    Shell
    7.990 Gs.
    Nafta Premium
    Copetrol
    8.290 Gs.
    Nafta Comun
    Petropar
    6.990 Gs.
    """

    prices = parse_fuel_prices_from_text(text, "https://www.combustibles.com.py/")

    assert {(item.brand, item.octane) for item in prices} == {("Shell", 95), ("Copetrol", 97)}
