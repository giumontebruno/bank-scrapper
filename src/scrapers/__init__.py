"""Scrapers."""

from scrapers.bnf import BNFScraper
from scrapers.continental import ContinentalScraper
from scrapers.itau import ItauScraper
from scrapers.sudameris import SudamerisScraper
from scrapers.ueno import UenoScraper

SCRAPER_REGISTRY = {
    "ueno": UenoScraper,
    "itau": ItauScraper,
    "sudameris": SudamerisScraper,
    "continental": ContinentalScraper,
    "bnf": BNFScraper,
}
