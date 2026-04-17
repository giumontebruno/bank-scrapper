from __future__ import annotations

from query.audit import build_audit_report
from query.repository import PromotionRepository
from scrapers import SCRAPER_REGISTRY
from scrapers.fuel_prices import FuelPriceCollector


def run_collect(repository: PromotionRepository, *, month: str, bank: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"month": month, "bank": bank}

    if bank is None:
        prices = FuelPriceCollector().collect()
        repository.save_fuel_prices(prices)
        payload["fuel_prices"] = len(prices)
        bank_results: dict[str, int] = {}
        bank_metrics: dict[str, dict[str, int]] = {}
        for bank_name, scraper_cls in SCRAPER_REGISTRY.items():
            scraper = scraper_cls()
            promotions, metrics = scraper.collect_with_metrics(month)
            repository.replace_promotions(_bank_label(bank_name), month, promotions)
            bank_results[bank_name] = len(promotions)
            bank_metrics[bank_name] = metrics.as_dict()
        payload["promotions"] = bank_results
        payload["scraper_metrics"] = bank_metrics
        payload["warnings"] = [issue.code for issue in build_audit_report(repository, month_ref=month).issues]
        return payload

    bank_key = bank.lower()
    if bank_key not in SCRAPER_REGISTRY:
        raise ValueError(f"Banco no soportado: {bank}")
    scraper = SCRAPER_REGISTRY[bank_key]()
    promotions, metrics = scraper.collect_with_metrics(month)
    repository.replace_promotions(_bank_label(bank_key), month, promotions)
    payload["promotions"] = len(promotions)
    payload["scraper_metrics"] = metrics.as_dict()
    payload["warnings"] = [issue.code for issue in build_audit_report(repository, month_ref=month, bank=_bank_label(bank_key)).issues]
    return payload


def _bank_label(bank_key: str) -> str:
    if bank_key == "bnf":
        return "BNF"
    return bank_key.title()
