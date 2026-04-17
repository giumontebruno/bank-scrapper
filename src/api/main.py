from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.collect import run_collect
from core.config import ConfigError, get_settings
from query.audit import build_audit_report
from query.engine import QueryEngine
from query.repository import PromotionRepository
from scrapers import SCRAPER_REGISTRY
from web.routes import register_web_routes


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
    def admin_collect(payload: dict[str, Any] | None = Body(None)) -> dict[str, object]:
        _ensure_admin_enabled(settings)
        payload = payload or {}
        month = payload.get("month")
        bank = payload.get("bank")
        if not month:
            raise HTTPException(status_code=400, detail="month es obligatorio")
        result = run_collect(get_repository(), month=month, bank=bank)
        return {"status": "ok", **result}

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

    register_web_routes(api, get_repository=get_repository)
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


app = create_app()
