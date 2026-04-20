from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from fastapi import BackgroundTasks, Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.collect import run_collect
from core.config import ConfigError, get_settings
from query.audit import build_audit_report
from query.engine import QueryEngine
from query.repository import PromotionRepository
from scrapers import SCRAPER_REGISTRY
from web.routes import register_web_routes


class CollectJobState:
    def __init__(self) -> None:
        self._lock = Lock()
        self._status = "idle"
        self._started_at: str | None = None
        self._finished_at: str | None = None
        self._last_error: str | None = None
        self._last_result: dict[str, object] | None = None
        self._month: str | None = None
        self._bank: str | None = None

    def try_start(self, *, month: str, bank: str | None) -> dict[str, object]:
        with self._lock:
            if self._status == "running":
                raise RuntimeError("collect ya está en ejecución")
            self._status = "running"
            self._started_at = _now_iso()
            self._finished_at = None
            self._last_error = None
            self._last_result = None
            self._month = month
            self._bank = bank
            return {"status": "started", "month": month, "bank": bank}

    def mark_done(self, *, result: dict[str, object]) -> None:
        with self._lock:
            self._status = "done"
            self._finished_at = _now_iso()
            self._last_result = result
            self._last_error = None

    def mark_error(self, *, error: str) -> None:
        with self._lock:
            self._status = "error"
            self._finished_at = _now_iso()
            self._last_error = error

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "status": self._status,
                "started_at": self._started_at,
                "finished_at": self._finished_at,
                "last_error": self._last_error,
                "last_result": self._last_result,
                "month": self._month,
                "bank": self._bank,
            }

    def reset(self) -> None:
        with self._lock:
            self._status = "idle"
            self._started_at = None
            self._finished_at = None
            self._last_error = None
            self._last_result = None
            self._month = None
            self._bank = None

    def is_running(self) -> bool:
        with self._lock:
            return self._status == "running"


_collect_job_state = CollectJobState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.repository = PromotionRepository.default()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    api = FastAPI(title="promo-query-py API", version="0.2.0", lifespan=lifespan)
    api.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @api.exception_handler(ConfigError)
    async def handle_config_error(_: Request, exc: ConfigError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"error": "config_error", "detail": str(exc)})

    @api.exception_handler(HTTPException)
    async def handle_http_error(_: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "request_error"
        return JSONResponse(status_code=exc.status_code, content={"error": "http_error", "detail": detail})

    @api.exception_handler(Exception)
    async def handle_generic_error(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"error": "internal_error", "detail": str(exc)})

    @api.get("/health")
    def health() -> dict[str, object]:
        repository = get_repository()
        report = build_audit_report(repository)
        return {
            "status": "ok" if report.api_readiness != "blocked" else "warning",
            "app_env": settings.app_env,
            "database_backend": repository.backend,
            "api_readiness": report.api_readiness,
            "api_readiness_reasons": report.api_readiness_reasons,
        }

    @api.get("/audit")
    def audit(month: str | None = None, bank: str | None = None, query: list[str] | None = None) -> dict[str, object]:
        report = build_audit_report(get_repository(), month_ref=month, bank=bank, queries=query)
        return report.dict()

    @api.get("/query")
    def query(text: str) -> dict[str, object]:
        return QueryEngine(get_repository()).query(text)

    @api.get("/banks")
    def banks(month: str | None = None) -> dict[str, object]:
        repository = get_repository()
        counts = repository.list_banks(month_ref=month)
        names = sorted(set(counts) | {_bank_label(name) for name in SCRAPER_REGISTRY})
        return {"month": month, "banks": names, "counts": counts}

    @api.get("/fuel-prices")
    def fuel_prices(month: str | None = None) -> dict[str, object]:
        items = [item.dict() for item in get_repository().list_fuel_prices(month_ref=month)]
        return {"month": month, "items": items}

    @api.get("/promotions")
    def promotions(
        month: str | None = None,
        bank: str | None = None,
        category: str | None = None,
        limit: int = 50,
    ) -> dict[str, object]:
        repository = get_repository()
        items = repository.list_promotions(month_ref=month, bank=bank, category=category, limit=limit)
        return {
            "month": month,
            "bank": bank,
            "category": category,
            "count": len(items),
            "items": [item.dict() for item in items],
        }

    @api.get("/categories")
    def categories(month: str | None = None, bank: str | None = None) -> dict[str, object]:
        report = build_audit_report(get_repository(), month_ref=month, bank=bank, queries=[])
        return {
            "month": month,
            "bank": bank,
            "covered_categories": report.dataset.covered_categories,
            "weak_categories": report.dataset.weak_categories,
            "counts": report.dataset.promotions_by_category,
            "banks": report.dataset.promotions_by_bank_category,
        }

    @api.post("/admin/collect")
    def admin_collect(
        background_tasks: BackgroundTasks,
        payload: dict[str, Any] | None = Body(None),
    ) -> dict[str, object]:
        _ensure_admin_enabled(settings)
        payload = payload or {}
        month = payload.get("month")
        bank = _normalize_bank(payload.get("bank"))
        if not month:
            raise HTTPException(status_code=400, detail="month es obligatorio")
        try:
            started = start_collect_job(background_tasks, month=month, bank=bank)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return started

    @api.get("/admin/collect/status")
    def admin_collect_status() -> dict[str, object]:
        _ensure_admin_enabled(settings)
        return get_collect_job_status()

    @api.post("/admin/audit")
    def admin_audit(payload: dict[str, Any] | None = Body(None)) -> dict[str, object]:
        _ensure_admin_enabled(settings)
        payload = payload or {}
        report = build_audit_report(
            get_repository(),
            month_ref=payload.get("month"),
            bank=payload.get("bank"),
            queries=payload.get("queries"),
        )
        return report.dict()

    register_web_routes(
        api,
        get_repository=get_repository,
        start_collect_job=start_collect_job,
        get_collect_job_status=get_collect_job_status,
    )
    return api


def get_repository() -> PromotionRepository:
    return PromotionRepository.default()


def _ensure_admin_enabled(settings: Any) -> None:
    if not settings.enable_admin_endpoints:
        raise HTTPException(status_code=403, detail="admin endpoints deshabilitados para este entorno")


def _bank_label(bank_key: str) -> str:
    if bank_key == "bnf":
        return "BNF"
    return bank_key.title()


def start_collect_job(background_tasks: BackgroundTasks, *, month: str, bank: str | None) -> dict[str, object]:
    started = _collect_job_state.try_start(month=month, bank=bank)
    background_tasks.add_task(_run_collect_job, month, bank)
    return started


def get_collect_job_status() -> dict[str, object]:
    return _collect_job_state.snapshot()


def reset_collect_job_state() -> None:
    _collect_job_state.reset()


def _run_collect_job(month: str, bank: str | None) -> None:
    try:
        result = run_collect(get_repository(), month=month, bank=bank)
    except Exception as exc:
        _collect_job_state.mark_error(error=str(exc))
        return
    try:
        _collect_job_state.mark_done(result=_compact_collect_result(result))
    except Exception as exc:
        # Proteccion defensiva: evita quedar en "running" si falla la serializacion del resultado.
        _collect_job_state.mark_error(error=f"error finalizando collect: {exc}")


def _compact_collect_result(result: dict[str, object]) -> dict[str, object]:
    compact: dict[str, object] = {
        "month": result.get("month"),
        "bank": result.get("bank"),
        "fuel_prices": result.get("fuel_prices", 0),
        "warnings": result.get("warnings", []),
    }
    promotions = result.get("promotions")
    if isinstance(promotions, dict):
        compact["promotions"] = promotions
        compact["banks_processed"] = sorted(promotions.keys())
        compact["promotions_total"] = sum(int(value) for value in promotions.values() if isinstance(value, (int, float)))
    elif isinstance(promotions, (int, float)):
        compact["promotions"] = int(promotions)
        compact["promotions_total"] = int(promotions)
        if result.get("bank"):
            compact["banks_processed"] = [str(result["bank"])]
    else:
        compact["promotions"] = promotions
    return compact


def _normalize_bank(raw_bank: object) -> str | None:
    if raw_bank is None:
        return None
    value = str(raw_bank).strip()
    if not value:
        return None
    key = value.lower()
    if key in SCRAPER_REGISTRY:
        return key
    if key == "bnf":
        return "bnf"
    titled = value.title()
    for bank_key in SCRAPER_REGISTRY:
        if _bank_label(bank_key).lower() == titled.lower():
            return bank_key
    raise HTTPException(status_code=400, detail=f"bank inválido: {raw_bank}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


app = create_app()
