from __future__ import annotations

from collections.abc import Callable

from query.audit import build_audit_report
from query.repository import PromotionRepository
from scrapers import SCRAPER_REGISTRY
from scrapers.fuel_prices import FuelPriceCollector


ProgressCallback = Callable[[dict[str, object]], None]


def run_collect(
    repository: PromotionRepository,
    *,
    month: str,
    bank: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"month": month, "bank": bank}

    if bank is None:
        _notify(progress_callback, current_step="Capturando precios de combustible", current_bank=None, completed_steps=0)
        prices = FuelPriceCollector().collect()
        repository.save_fuel_prices(prices)
        payload["fuel_prices"] = len(prices)
        bank_results: dict[str, int] = {}
        bank_metrics: dict[str, dict[str, int]] = {}
        for index, (bank_name, scraper_cls) in enumerate(SCRAPER_REGISTRY.items(), start=1):
            _notify(
                progress_callback,
                current_step=f"Procesando {_bank_label(bank_name)}",
                current_bank=bank_name,
                completed_steps=index,
            )
            scraper = scraper_cls()
            promotions, metrics = scraper.collect_with_metrics(month)
            repository.replace_promotions(_bank_label(bank_name), month, promotions)
            bank_results[bank_name] = len(promotions)
            bank_metrics[bank_name] = metrics.as_dict()
            _notify(
                progress_callback,
                current_step=f"{_bank_label(bank_name)} persistido",
                current_bank=bank_name,
                completed_steps=index + 1,
            )
        _notify(progress_callback, current_step="Calculando audit y warnings", current_bank=None, completed_steps=len(SCRAPER_REGISTRY) + 1)
        payload["promotions"] = bank_results
        payload["scraper_metrics"] = bank_metrics
        payload["bank_diagnostics"] = _bank_diagnostics(bank_results, bank_metrics)
        payload["warnings"] = [issue.code for issue in build_audit_report(repository, month_ref=month).issues]
        return payload

    bank_key = bank.lower()
    if bank_key not in SCRAPER_REGISTRY:
        raise ValueError(f"Banco no soportado: {bank}")
    _notify(progress_callback, current_step=f"Discovery y parsing de {_bank_label(bank_key)}", current_bank=bank_key, completed_steps=1)
    scraper = SCRAPER_REGISTRY[bank_key]()
    promotions, metrics = scraper.collect_with_metrics(month)
    _notify(progress_callback, current_step=f"Persistiendo {_bank_label(bank_key)}", current_bank=bank_key, completed_steps=2)
    repository.replace_promotions(_bank_label(bank_key), month, promotions)
    payload["promotions"] = len(promotions)
    payload["scraper_metrics"] = metrics.as_dict()
    payload["bank_diagnostics"] = _bank_diagnostics({bank_key: len(promotions)}, {bank_key: metrics.as_dict()})
    _notify(progress_callback, current_step="Calculando audit y warnings", current_bank=bank_key, completed_steps=3)
    payload["warnings"] = [issue.code for issue in build_audit_report(repository, month_ref=month, bank=_bank_label(bank_key)).issues]
    return payload


def _bank_label(bank_key: str) -> str:
    if bank_key == "bnf":
        return "BNF"
    return bank_key.title()


def _bank_diagnostics(results: dict[str, int], metrics: dict[str, dict[str, int]]) -> dict[str, str]:
    diagnostics: dict[str, str] = {}
    for bank_name, count in results.items():
        bank_metrics = metrics.get(bank_name, {})
        if count > 0:
            diagnostics[bank_name] = "ok"
        elif bank_metrics.get("discovery_candidates_count", 0) == 0:
            diagnostics[bank_name] = "no_sources_discovered"
        elif bank_metrics.get("parsed_blocks_count", 0) == 0:
            diagnostics[bank_name] = "sources_discovered_but_no_blocks"
        elif bank_metrics.get("filtered_blocks_count", 0) >= bank_metrics.get("parsed_blocks_count", 0):
            diagnostics[bank_name] = "all_blocks_filtered"
        else:
            diagnostics[bank_name] = "no_promotions_persisted"
    return diagnostics


def _notify(progress_callback: ProgressCallback | None, **payload: object) -> None:
    if progress_callback is not None:
        progress_callback(payload)
