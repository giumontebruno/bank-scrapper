from pathlib import Path

from scrapers.bnf import BNFScraper
from scrapers.continental import ContinentalScraper
from scrapers.common import extract_pdf_text
from scrapers.itau import ItauScraper
from scrapers.sudameris import SudamerisScraper
from scrapers.ueno import UenoScraper


class FakeResponse:
    def __init__(self, url: str, text: str | None = None, content: bytes | None = None, content_type: str = "text/html") -> None:
        self.url = url
        self.text = text or ""
        self.content = content or b""
        self.headers = {"content-type": content_type}

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, responses: dict[str, FakeResponse]) -> None:
        self.responses = responses

    def get(self, url: str, timeout: int = 20) -> FakeResponse:
        return self.responses[url]


def test_ueno_scraper_collects_html_and_pdf(monkeypatch) -> None:
    config = {
        "ueno": {
            "allowed_domains": ["www.ueno.com.py"],
            "detail_hints": ["promos", ".pdf"],
            "merchant_category_hints": {"shell": "combustible", "biggie": "supermercados"},
            "sources": [{"url": "https://www.ueno.com.py/", "source_type": "html_listing"}],
        }
    }
    responses = {
        "https://www.ueno.com.py/": FakeResponse(
            "https://www.ueno.com.py/",
            text=Path("tests/fixtures/ueno_listing.html").read_text(encoding="utf-8"),
        ),
        "https://www.ueno.com.py/promos/shell-detail": FakeResponse(
            "https://www.ueno.com.py/promos/shell-detail",
            text=Path("tests/fixtures/ueno_detail.html").read_text(encoding="utf-8"),
        ),
        "https://www.ueno.com.py/wp-content/uploads/2026/04/ueno-campana.pdf": FakeResponse(
            "https://www.ueno.com.py/wp-content/uploads/2026/04/ueno-campana.pdf",
            content=b"ueno-pdf",
            content_type="application/pdf",
        ),
    }
    monkeypatch.setattr("scrapers.common.extract_pdf_text", lambda payload: Path("tests/fixtures/ueno_pdf.txt").read_text(encoding="utf-8"))

    promotions = UenoScraper(session=FakeSession(responses), config=config).collect("2026-04")

    assert len(promotions) >= 2
    assert any(item.brand_normalized == "Shell" for item in promotions)
    assert any(item.merchant_normalized == "Biggie" for item in promotions)


def test_ueno_scraper_uses_sitemap_for_month_and_exposes_metrics(monkeypatch) -> None:
    config = {
        "ueno": {
            "allowed_domains": ["www.ueno.com.py"],
            "detail_hints": ["beneficio-byc", ".pdf"],
            "merchant_category_hints": {"biggie": "supermercados", "petropar": "combustible"},
            "sources": [
                {"url": "https://www.ueno.com.py/beneficios-sitemap.xml", "source_type": "sitemap"},
            ],
        }
    }
    responses = {
        "https://www.ueno.com.py/beneficios-sitemap.xml": FakeResponse(
            "https://www.ueno.com.py/beneficios-sitemap.xml",
            text="""
            <urlset>
              <url><loc>https://www.ueno.com.py/beneficio-byc/abr2026/biggie/</loc></url>
              <url><loc>https://www.ueno.com.py/beneficio-byc/mar2026/stock/</loc></url>
            </urlset>
            """,
            content_type="text/xml",
        ),
        "https://www.ueno.com.py/beneficio-byc/abr2026/biggie/": FakeResponse(
            "https://www.ueno.com.py/beneficio-byc/abr2026/biggie/",
            text="""
            <html><body>
              <iframe src="https://www.ueno.com.py/wp-content/uploads/2026/04/ueno-biggie.pdf"></iframe>
              <a href="https://www.ueno.com.py/wp-content/uploads/2026/04/ueno-biggie.pdf">Descargar pdf</a>
            </body></html>
            """,
        ),
        "https://www.ueno.com.py/wp-content/uploads/2026/04/ueno-biggie.pdf": FakeResponse(
            "https://www.ueno.com.py/wp-content/uploads/2026/04/ueno-biggie.pdf",
            content=b"ueno-pdf",
            content_type="application/pdf",
        ),
    }
    monkeypatch.setattr(
        "scrapers.common.extract_pdf_text",
        lambda payload: "Biggie\n20% de reintegro\nVigencia: 01/04/2026 al 30/04/2026\nAplica a debito",
    )

    promotions, metrics = UenoScraper(session=FakeSession(responses), config=config).collect_with_metrics("2026-04")

    assert promotions
    assert promotions[0].merchant_normalized == "Biggie"
    assert metrics.discovery_candidates_count >= 2
    assert metrics.parsed_blocks_count >= 1
    assert metrics.persisted_promotions_count == len(promotions)


def test_ueno_metrics_distinguish_discovery_without_persisted_promos(monkeypatch) -> None:
    config = {
        "ueno": {
            "allowed_domains": ["www.ueno.com.py"],
            "detail_hints": ["beneficio-byc", ".pdf"],
            "merchant_category_hints": {"biggie": "supermercados"},
            "sources": [{"url": "https://www.ueno.com.py/beneficios-sitemap.xml", "source_type": "sitemap"}],
        }
    }
    responses = {
        "https://www.ueno.com.py/beneficios-sitemap.xml": FakeResponse(
            "https://www.ueno.com.py/beneficios-sitemap.xml",
            text="<urlset><url><loc>https://www.ueno.com.py/beneficio-byc/abr2026/biggie/</loc></url></urlset>",
            content_type="text/xml",
        ),
        "https://www.ueno.com.py/beneficio-byc/abr2026/biggie/": FakeResponse(
            "https://www.ueno.com.py/beneficio-byc/abr2026/biggie/",
            text='<html><body><a href="https://www.ueno.com.py/wp-content/uploads/2026/04/ueno-biggie.pdf">Descargar pdf</a></body></html>',
        ),
        "https://www.ueno.com.py/wp-content/uploads/2026/04/ueno-biggie.pdf": FakeResponse(
            "https://www.ueno.com.py/wp-content/uploads/2026/04/ueno-biggie.pdf",
            content=b"ueno-pdf",
            content_type="application/pdf",
        ),
    }
    monkeypatch.setattr("scrapers.common.extract_pdf_text", lambda payload: "Documento informativo sin beneficio promocional")

    promotions, metrics = UenoScraper(session=FakeSession(responses), config=config).collect_with_metrics("2026-04")

    assert promotions == []
    assert metrics.discovery_candidates_count >= 2
    assert metrics.parsed_blocks_count >= 1
    assert metrics.persisted_promotions_count == 0


def test_ueno_scraper_ignores_operational_pdf_blocks(monkeypatch) -> None:
    config = {
        "ueno": {
            "allowed_domains": ["www.ueno.com.py"],
            "detail_hints": ["beneficio-byc", ".pdf"],
            "merchant_category_hints": {"biggie": "supermercados"},
            "sources": [{"url": "https://www.ueno.com.py/beneficios-sitemap.xml", "source_type": "sitemap"}],
        }
    }
    responses = {
        "https://www.ueno.com.py/beneficios-sitemap.xml": FakeResponse(
            "https://www.ueno.com.py/beneficios-sitemap.xml",
            text="<urlset><url><loc>https://www.ueno.com.py/beneficio-byc/abr2026/biggie/</loc></url></urlset>",
            content_type="text/xml",
        ),
        "https://www.ueno.com.py/beneficio-byc/abr2026/biggie/": FakeResponse(
            "https://www.ueno.com.py/beneficio-byc/abr2026/biggie/",
            text='<html><body><a href="https://www.ueno.com.py/wp-content/uploads/2026/04/ueno-biggie.pdf">Descargar pdf</a></body></html>',
        ),
        "https://www.ueno.com.py/wp-content/uploads/2026/04/ueno-biggie.pdf": FakeResponse(
            "https://www.ueno.com.py/wp-content/uploads/2026/04/ueno-biggie.pdf",
            content=b"ueno-pdf",
            content_type="application/pdf",
        ),
    }
    monkeypatch.setattr(
        "scrapers.common.extract_pdf_text",
        lambda payload: (
            "Biggie\n20% de reintegro\nVigencia: 01/04/2026 al 30/04/2026\n\n"
            "Plazo de acreditacion del reintegro:\nTarjetas de credito: hasta 8 dias habiles.\n"
            "Comunicaciones:\nNotificaciones en la aplicacion movil del banco.\n"
            "ANEXO I\nNombre del comercio adherido\nPagina web https www ueno com py"
        ),
    )

    promotions = UenoScraper(session=FakeSession(responses), config=config).collect("2026-04")

    assert promotions
    assert all((item.merchant_normalized or "") not in {"Comunicaciones", "Pagina Web Https Www Ueno Com Py"} for item in promotions)


def test_ueno_scraper_does_not_use_corporate_issuer_as_merchant(monkeypatch) -> None:
    config = {
        "ueno": {
            "allowed_domains": ["www.ueno.com.py"],
            "merchant_category_hints": {"biggie": "supermercados"},
            "sources": [{"url": "https://www.ueno.com.py/beneficios-sitemap.xml", "source_type": "sitemap"}],
        }
    }
    responses = {
        "https://www.ueno.com.py/beneficios-sitemap.xml": FakeResponse(
            "https://www.ueno.com.py/beneficios-sitemap.xml",
            text="<urlset><url><loc>https://www.ueno.com.py/beneficio-byc/abr2026/biggie/</loc></url></urlset>",
            content_type="text/xml",
        ),
        "https://www.ueno.com.py/beneficio-byc/abr2026/biggie/": FakeResponse(
            "https://www.ueno.com.py/beneficio-byc/abr2026/biggie/",
            text='<html><body><a href="https://www.ueno.com.py/wp-content/uploads/2026/04/ueno-biggie.pdf">Descargar pdf</a></body></html>',
        ),
        "https://www.ueno.com.py/wp-content/uploads/2026/04/ueno-biggie.pdf": FakeResponse(
            "https://www.ueno.com.py/wp-content/uploads/2026/04/ueno-biggie.pdf",
            content=b"ueno-pdf",
            content_type="application/pdf",
        ),
    }
    monkeypatch.setattr(
        "scrapers.common.extract_pdf_text",
        lambda payload: "Ueno Bank S A\nBiggie\n20% de reintegro\nVigencia: 01/04/2026 al 30/04/2026",
    )

    promotions = UenoScraper(session=FakeSession(responses), config=config).collect("2026-04")

    assert promotions
    assert promotions[0].merchant_normalized == "Biggie"


def test_ueno_discovery_excludes_cta_links() -> None:
    scraper = UenoScraper(
        session=FakeSession({}),
        config={
            "ueno": {
                "allowed_domains": ["www.ueno.com.py"],
                "detail_hints": ["promo", ".pdf"],
                "exclude_url_hints": ["conoce-mas", "conocer-promos"],
                "exclude_link_text_hints": ["conoce mas", "conocer promos", "ver mas"],
            }
        },
    )

    html = """
    <html><body>
      <a href="/promos/shell">Promo Shell</a>
      <a href="/landing/conoce-mas-ueno">Conoce mas sobre Ueno</a>
      <a href="/promos/conocer-promos">Conocer promos</a>
    </body></html>
    """
    links = scraper._discover_links(html, "https://www.ueno.com.py/", {"www.ueno.com.py"})

    assert links == ["https://www.ueno.com.py/promos/shell"]
def test_itau_scraper_collects_html_and_pdf(monkeypatch) -> None:
    config = {
        "itau": {
            "allowed_domains": ["www.itau.com.py"],
            "detail_hints": ["promos", ".pdf"],
            "merchant_category_hints": {"copetrol": "combustible", "ferrex": "ferreteria"},
            "sources": [{"url": "https://www.itau.com.py/promociones", "source_type": "html_listing"}],
        }
    }
    responses = {
        "https://www.itau.com.py/promociones": FakeResponse(
            "https://www.itau.com.py/promociones",
            text=Path("tests/fixtures/itau_listing.html").read_text(encoding="utf-8"),
        ),
        "https://www.itau.com.py/promos/copetrol-detalle": FakeResponse(
            "https://www.itau.com.py/promos/copetrol-detalle",
            text=Path("tests/fixtures/itau_detail.html").read_text(encoding="utf-8"),
        ),
        "https://www.itau.com.py/Content/archivos/Dinamicos/itau-beneficios.pdf": FakeResponse(
            "https://www.itau.com.py/Content/archivos/Dinamicos/itau-beneficios.pdf",
            content=b"itau-pdf",
            content_type="application/pdf",
        ),
    }
    monkeypatch.setattr("scrapers.common.extract_pdf_text", lambda payload: Path("tests/fixtures/itau_pdf.txt").read_text(encoding="utf-8"))

    promotions = ItauScraper(session=FakeSession(responses), config=config).collect("2026-04")

    assert len(promotions) >= 2
    assert any(item.brand_normalized == "Copetrol" for item in promotions)
    assert any(item.merchant_normalized == "Ferrex" for item in promotions)


def test_itau_scraper_ignores_disclaimer_as_merchant() -> None:
    scraper = ItauScraper(
        session=FakeSession({}),
        config={"itau": {"merchant_category_hints": {"copetrol": "combustible", "ferrex": "ferreteria"}}},
    )

    merchant = scraper.extract_merchant(
        "No aplica para servicios a domicilio y la compra de giftcard.\n15% de reintegro en Ferrex.",
        title="No aplica para servicios a domicilio y la compra de giftcard",
    )

    assert merchant == "ferrex"


def test_itau_scraper_rejects_repeated_heading_and_single_letter_merchants() -> None:
    scraper = ItauScraper(
        session=FakeSession({}),
        config={"itau": {"merchant_category_hints": {"ferrex": "ferreteria"}}},
    )

    repeated = scraper.extract_merchant("Ppprrrooommmoooccciiiooonnneeesss\n20% de descuento", title="Ppprrrooommmoooccciiiooonnneeesss")
    single = scraper.extract_merchant("P\n20% de descuento en ferreteria", title="P")

    assert repeated is None
    assert single is None


def test_sudameris_scraper_collects_html_and_pdf(monkeypatch) -> None:
    config = {
        "sudameris": {
            "allowed_domains": ["www.sudameris.com.py"],
            "detail_hints": ["promociones", ".pdf"],
            "merchant_category_hints": {"super": "supermercados", "ferreteria": "ferreteria"},
            "sources": [{"url": "https://www.sudameris.com.py/personas/beneficios", "source_type": "html_listing"}],
        }
    }
    responses = {
        "https://www.sudameris.com.py/personas/beneficios": FakeResponse(
            "https://www.sudameris.com.py/personas/beneficios",
            text=Path("tests/fixtures/sudameris_listing.html").read_text(encoding="utf-8"),
        ),
        "https://www.sudameris.com.py/promociones/super6-detalle": FakeResponse(
            "https://www.sudameris.com.py/promociones/super6-detalle",
            text=Path("tests/fixtures/sudameris_detail.html").read_text(encoding="utf-8"),
        ),
        "https://www.sudameris.com.py/storage/app/uploads/public/sudameris-zonal.pdf": FakeResponse(
            "https://www.sudameris.com.py/storage/app/uploads/public/sudameris-zonal.pdf",
            content=b"sudameris-pdf",
            content_type="application/pdf",
        ),
    }
    monkeypatch.setattr(
        "scrapers.common.extract_pdf_text",
        lambda payload: Path("tests/fixtures/sudameris_pdf.txt").read_text(encoding="utf-8"),
    )

    promotions = SudamerisScraper(session=FakeSession(responses), config=config).collect("2026-04")

    assert len(promotions) >= 2
    assert any(item.merchant_normalized == "Superseis" for item in promotions)
    assert any(item.merchant_normalized == "Ferreteria Don Juan" for item in promotions)


def test_sudameris_scraper_discards_placeholder_title_as_merchant() -> None:
    scraper = SudamerisScraper(
        session=FakeSession({}),
        config={"sudameris": {"merchant_category_hints": {"biggie": "supermercados", "copetrol": "combustible"}}},
    )

    merchant = scraper.extract_merchant("...\n20% de reintegro en Biggie.", title="...")

    assert merchant == "Biggie"


def test_continental_scraper_collects_embedded_html_and_pdf(monkeypatch) -> None:
    config = {
        "continental": {
            "allowed_domains": ["ayuda.bancontinental.com.py", "www.bancontinental.com.py"],
            "detail_hints": ["promociones-tc", "guia-de-beneficios", ".pdf"],
            "merchant_category_hints": {
                "supermercados": "supermercados",
                "combustible": "combustible",
                "gastronomia": "gastronomia",
                "shell": "combustible",
                "stock": "supermercados",
            },
            "sources": [
                {
                    "url": "https://ayuda.bancontinental.com.py/help-center-front/topicos-de-ayuda/tarjetas/promociones-tc",
                    "source_type": "html_listing",
                }
            ],
        }
    }
    responses = {
        "https://ayuda.bancontinental.com.py/help-center-front/topicos-de-ayuda/tarjetas/promociones-tc": FakeResponse(
            "https://ayuda.bancontinental.com.py/help-center-front/topicos-de-ayuda/tarjetas/promociones-tc",
            text=Path("tests/fixtures/continental_listing.html").read_text(encoding="utf-8"),
        ),
        "https://ayuda.bancontinental.com.py/help-center-front/topicos-de-ayuda/tarjetas/promociones-tc/calendario-de-promociones": FakeResponse(
            "https://ayuda.bancontinental.com.py/help-center-front/topicos-de-ayuda/tarjetas/promociones-tc/calendario-de-promociones",
            text=Path("tests/fixtures/continental_calendar.html").read_text(encoding="utf-8"),
        ),
        "https://ayuda.bancontinental.com.py/help-center-front/topicos-de-ayuda/tarjetas/promociones-tc/guia-de-beneficios-con-tarjeta-de-credito": FakeResponse(
            "https://ayuda.bancontinental.com.py/help-center-front/topicos-de-ayuda/tarjetas/promociones-tc/guia-de-beneficios-con-tarjeta-de-credito",
            text=Path("tests/fixtures/continental_guide.html").read_text(encoding="utf-8"),
        ),
        "https://www.bancontinental.com.py/api/uploads/guia.pdf": FakeResponse(
            "https://www.bancontinental.com.py/api/uploads/guia.pdf",
            content=b"continental-pdf",
            content_type="application/pdf",
        ),
    }
    monkeypatch.setattr(
        "scrapers.common.extract_pdf_text",
        lambda payload: Path("tests/fixtures/continental_pdf.txt").read_text(encoding="utf-8"),
    )

    promotions = ContinentalScraper(session=FakeSession(responses), config=config).collect("2026-04")

    assert any(item.category == "combustible" and item.discount_percent == 25 for item in promotions)
    assert any(item.category == "supermercados" and item.discount_percent == 30 for item in promotions)
    assert any(item.brand_normalized == "Shell" for item in promotions)


def test_continental_scraper_keeps_category_useful_when_merchant_is_generic() -> None:
    scraper = ContinentalScraper(
        session=FakeSession({}),
        config={"continental": {"merchant_category_hints": {"combustible": "combustible", "shell": "combustible"}}},
    )
    block = type(
        "Block",
        (),
        {
            "title": "Viernes: Hasta 25% en combustible",
            "text": "Viernes: Hasta 25% en combustible",
            "source_type": "html_detail",
            "source_url": "https://example.com/continental",
        },
    )()

    promotion = scraper.parse_block(block, "2026-04")

    assert promotion is not None
    assert promotion.category == "combustible"
    assert promotion.merchant_normalized is None


def test_bnf_scraper_collects_vouchers_and_pdf(monkeypatch) -> None:
    config = {
        "bnf": {
            "allowed_domains": ["bnficios.bnf.gov.py", "www.bnf.gov.py"],
            "detail_hints": ["producto/", "pdf"],
            "merchant_category_hints": {
                "petrobras": "combustible",
                "superseis": "supermercados",
                "stock": "supermercados",
                "farmacias": "salud",
            },
            "sources": [{"url": "https://bnficios.bnf.gov.py/", "source_type": "html_listing"}],
        }
    }
    responses = {
        "https://bnficios.bnf.gov.py/": FakeResponse(
            "https://bnficios.bnf.gov.py/",
            text=Path("tests/fixtures/bnf_home.html").read_text(encoding="utf-8"),
        ),
        "https://bnficios.bnf.gov.py/producto/241/vale-de-combustible-petrobras-de-gs-200-000": FakeResponse(
            "https://bnficios.bnf.gov.py/producto/241/vale-de-combustible-petrobras-de-gs-200-000",
            text=Path("tests/fixtures/bnf_product_petrobras.html").read_text(encoding="utf-8"),
        ),
        "https://bnficios.bnf.gov.py/producto/747/vale-de-compra-superseis-100-000-gs": FakeResponse(
            "https://bnficios.bnf.gov.py/producto/747/vale-de-compra-superseis-100-000-gs",
            text=Path("tests/fixtures/bnf_product_superseis.html").read_text(encoding="utf-8"),
        ),
        "https://bnficios.bnf.gov.py/producto/3013/vale-de-compra-stock-200-000-gs": FakeResponse(
            "https://bnficios.bnf.gov.py/producto/3013/vale-de-compra-stock-200-000-gs",
            text=Path("tests/fixtures/bnf_product_stock.html").read_text(encoding="utf-8"),
        ),
        "https://www.bnf.gov.py/uploads/Promocion_Reintegro_Farmacias_2025_b1ef6ef0bb.pdf": FakeResponse(
            "https://www.bnf.gov.py/uploads/Promocion_Reintegro_Farmacias_2025_b1ef6ef0bb.pdf",
            content=b"bnf-pdf",
            content_type="application/pdf",
        ),
    }
    monkeypatch.setattr(
        "scrapers.common.extract_pdf_text",
        lambda payload: Path("tests/fixtures/bnf_pdf.txt").read_text(encoding="utf-8"),
    )

    promotions = BNFScraper(session=FakeSession(responses), config=config).collect("2026-04")

    assert any(item.bank == "BNF" for item in promotions)
    assert any(item.brand_normalized == "Petrobras" for item in promotions)
    assert any(item.merchant_normalized == "Superseis" for item in promotions)
    assert any(item.cashback_percent == 30 for item in promotions)
