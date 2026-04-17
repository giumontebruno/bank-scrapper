from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from scrapers.common import BaseBankScraper, DownloadedSource

_MONTH_SLUGS = {
    "01": "ene",
    "02": "feb",
    "03": "mar",
    "04": "abr",
    "05": "may",
    "06": "jun",
    "07": "jul",
    "08": "ago",
    "09": "sep",
    "10": "oct",
    "11": "nov",
    "12": "dic",
}


class UenoScraper(BaseBankScraper):
    bank_name = "ueno"

    def discover_sources(self, month_ref: str | None = None) -> list[DownloadedSource]:
        discovered: dict[tuple[str, str], DownloadedSource] = {}

        for source in super().discover_sources(month_ref=month_ref):
            if source.source_type == "sitemap":
                continue
            discovered[(source.url, source.source_type)] = source

        sitemap_urls = [item["url"] for item in self.bank_config.get("sources", []) if item["source_type"] == "sitemap"]
        if not sitemap_urls or not month_ref:
            return list(discovered.values())

        month_slug = self._month_slug(month_ref)
        allowed_domains = set(self.bank_config.get("allowed_domains", []))
        for sitemap_url in sitemap_urls:
            for detail_url in self._benefit_urls_from_sitemap(sitemap_url, month_slug):
                if allowed_domains and urlparse(detail_url).netloc not in allowed_domains:
                    continue
                detail_source = self.fetch_source(detail_url, source_type="html_detail")
                if detail_source is None:
                    continue
                discovered[(detail_source.url, detail_source.source_type)] = detail_source
                if detail_source.text:
                    for pdf_url in self._pdf_links_from_html(detail_source.text, detail_source.url):
                        pdf_source = self.fetch_source(pdf_url, source_type="pdf_campaign")
                        if pdf_source is not None:
                            discovered[(pdf_source.url, pdf_source.source_type)] = pdf_source

        return list(discovered.values())

    def _benefit_urls_from_sitemap(self, sitemap_url: str, month_slug: str) -> list[str]:
        response = self.session.get(sitemap_url, timeout=self.timeout)
        response.raise_for_status()
        urls = re.findall(r"<loc>(.*?)</loc>", response.text)
        month_segment = f"/beneficio-byc/{month_slug}/"
        results: list[str] = []
        for url in urls:
            if month_segment not in url:
                continue
            if url.rstrip("/").endswith(f"/{month_slug}"):
                continue
            results.append(url)
        return results

    def _pdf_links_from_html(self, html: str, base_url: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        links: list[str] = []
        for tag in soup.find_all(["a", "iframe"]):
            href = tag.get("href") or tag.get("src")
            if not href or ".pdf" not in href.lower():
                continue
            links.append(href)
        return list(dict.fromkeys(links))

    @staticmethod
    def _month_slug(month_ref: str) -> str:
        year, month = month_ref.split("-")
        return f"{_MONTH_SLUGS[month]}{year}"
