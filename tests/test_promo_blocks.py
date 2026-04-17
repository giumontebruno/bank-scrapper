from pathlib import Path

from parsers.promo_blocks import embedded_html_promo_blocks, html_promo_blocks, text_promo_blocks


def test_html_promo_blocks_segment_cards() -> None:
    html = Path("tests/fixtures/ueno_listing.html").read_text(encoding="utf-8")
    blocks = html_promo_blocks(html, source_url="https://example.com", source_type="html_listing")

    assert len(blocks) >= 1
    assert any("Shell Mcal Lopez" in block.text for block in blocks)


def test_text_promo_blocks_split_multipromo_text() -> None:
    text = "Promo A\n10% descuento\n\nPromo B\n20% cashback\n\nPromo C\n6 cuotas"
    blocks = text_promo_blocks(text, source_url="https://example.com/file.pdf", source_type="pdf_campaign")

    assert len(blocks) == 3
    assert blocks[1].title == "Promo B"


def test_embedded_html_promo_blocks_extract_rsc_fragments() -> None:
    html = Path("tests/fixtures/continental_calendar.html").read_text(encoding="utf-8")
    blocks = embedded_html_promo_blocks(
        html,
        source_url="https://ayuda.bancontinental.com.py/help-center-front/topicos-de-ayuda/tarjetas/promociones-tc/calendario-de-promociones",
        source_type="html_detail",
    )

    assert blocks
    assert any("30% en supermercados" in block.text for block in blocks)
