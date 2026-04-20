from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.config import get_settings
from query.audit import build_audit_report
from query.engine import QueryEngine
from query.repository import PromotionRepository
from scrapers import SCRAPER_REGISTRY
from web.view_models import (
    EXAMPLE_QUERIES,
    PROMO_TYPES,
    QUALITY_LABELS,
    SearchFilters,
    apply_match_filters,
    apply_promotion_filters,
    build_empty_state,
    fuel_recommendations,
    normalize_recent_queries,
    now_month_ref,
    paginate,
    promotion_card,
    summarize_match_kind,
    timed_call,
    update_recent_queries,
    validate_bank,
    validate_month,
)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
RECENT_SEARCH_COOKIE = "promo_recent_queries"


def register_web_routes(
    app: FastAPI,
    *,
    get_repository: Callable[[], PromotionRepository],
    start_collect_job: Callable[..., dict[str, object]],
    get_collect_job_status: Callable[[], dict[str, object]],
) -> None:
    app.mount("/web/static", StaticFiles(directory=str(STATIC_DIR)), name="web-static")

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        recent_queries = normalize_recent_queries(request.cookies.get(RECENT_SEARCH_COOKIE))
        return templates.TemplateResponse(
            request,
            "home.html",
            {
                "title": "Promo Query Paraguay",
                "active_nav": "home",
                "example_queries": EXAMPLE_QUERIES,
                "recent_queries": recent_queries,
                "default_month": now_month_ref(),
            },
        )

    @app.get("/search", response_class=HTMLResponse)
    def search(
        request: Request,
        q: str = "",
        bank: str = "",
        category: str = "",
        quality: str = "",
        promo_type: str = "",
    ) -> HTMLResponse:
        payload = {"query": q, "matches": []}
        repository = get_repository()
        if q.strip():
            payload = QueryEngine(repository).query(q)

        filters = SearchFilters(bank=bank, category=category, quality=quality, promo_type=promo_type)
        filtered = apply_match_filters(payload["matches"], filters)
        categories = sorted({item.get("category") for item in payload["matches"] if item.get("category")})
        banks = sorted({item.get("bank") for item in payload["matches"] if item.get("bank")})
        recent_queries = normalize_recent_queries(request.cookies.get(RECENT_SEARCH_COOKIE))
        empty_state = build_empty_state(q, payload["matches"], filtered)

        response = templates.TemplateResponse(
            request,
            "search.html",
            {
                "title": "Resultados",
                "active_nav": "search",
                "query": q,
                "matches": filtered,
                "total_matches": len(payload["matches"]),
                "visible_matches": len(filtered),
                "filters": filters,
                "categories": categories,
                "banks": banks,
                "quality_labels": QUALITY_LABELS,
                "promo_types": PROMO_TYPES,
                "result_kind": summarize_match_kind,
                "example_queries": EXAMPLE_QUERIES,
                "recent_queries": recent_queries,
                "empty_state": empty_state,
            },
        )
        if q.strip():
            response.set_cookie(
                RECENT_SEARCH_COOKIE,
                json.dumps(update_recent_queries(recent_queries, q), ensure_ascii=False),
                max_age=60 * 60 * 24 * 30,
                httponly=False,
                samesite="lax",
            )
        return response

    @app.get("/audit-ui", response_class=HTMLResponse)
    def audit_ui(
        request: Request,
        month: str | None = None,
        bank: str | None = None,
        query: str = "",
        error: str = "",
    ) -> HTMLResponse:
        report = None
        issues: list[str] = []
        try:
            safe_month = validate_month(month)
            safe_bank = validate_bank(bank, set(SCRAPER_REGISTRY) | {"BNF", "Ueno", "Itau", "Sudameris", "Continental"})
            report = build_audit_report(
                get_repository(),
                month_ref=safe_month,
                bank=safe_bank,
                queries=[query] if query.strip() else None,
            )
        except ValueError as exc:
            issues.append(str(exc))

        return templates.TemplateResponse(
            request,
            "audit.html",
            {
                "title": "Estado del dataset",
                "active_nav": "audit",
                "report": report,
                "error_message": error or (issues[0] if issues else ""),
                "month": month or "",
                "bank": bank or "",
                "query_text": query,
                "banks": sorted({_bank_label(key) for key in SCRAPER_REGISTRY}),
            },
        )

    @app.post("/audit-ui", response_class=HTMLResponse)
    def audit_ui_submit(
        request: Request,
        month: str = Form(""),
        bank: str = Form(""),
        query: str = Form(""),
    ) -> HTMLResponse:
        return audit_ui(request, month=month, bank=bank, query=query)

    @app.get("/fuel", response_class=HTMLResponse)
    def fuel_view(request: Request, month: str | None = None, brand: str = "", octane: str = "") -> HTMLResponse:
        error_message = ""
        repository = get_repository()
        safe_month = None
        try:
            safe_month = validate_month(month)
        except ValueError as exc:
            error_message = str(exc)

        items = repository.list_fuel_prices(month_ref=safe_month)
        brands = sorted({item.brand for item in repository.list_fuel_prices(month_ref=safe_month)})
        if brand:
            items = [item for item in items if item.brand.lower() == brand.lower()]
        if octane in {"95", "97"}:
            items = [item for item in items if str(item.octane) == octane]

        query_engine = QueryEngine(repository)
        recs = fuel_recommendations(
            query_engine.query("que tarjeta me conviene para 95")["matches"],
            query_engine.query("que tarjeta me conviene para 97")["matches"],
        )
        grouped: dict[str, list[object]] = {}
        for item in items:
            grouped.setdefault(item.brand, []).append(item)
        return templates.TemplateResponse(
            request,
            "fuel.html",
            {
                "title": "Combustibles",
                "active_nav": "fuel",
                "month": safe_month or month,
                "brand": brand,
                "octane": octane,
                "items": items,
                "grouped_items": grouped,
                "brands": brands,
                "recommendations": recs,
                "error_message": error_message,
            },
        )

    @app.get("/promotions-ui", response_class=HTMLResponse)
    def promotions_ui(
        request: Request,
        month: str | None = None,
        bank: str = "",
        category: str = "",
        promo_type: str = "",
        quality: str = "",
        page: int = 1,
        limit: int = 12,
    ) -> HTMLResponse:
        error_message = ""
        repository = get_repository()
        try:
            safe_month = validate_month(month)
        except ValueError as exc:
            safe_month = None
            error_message = str(exc)

        raw_items = repository.list_promotions(month_ref=safe_month, limit=200)
        cards = [promotion_card(item) for item in raw_items]
        cards = apply_promotion_filters(cards, bank=bank, category=category, promo_type=promo_type, quality=quality)
        page_items, total_pages = paginate(cards, page=page, page_size=max(1, min(limit, 24)))

        audit = build_audit_report(repository, month_ref=safe_month, queries=[])
        banks = sorted(audit.dataset.promotions_by_bank)
        return templates.TemplateResponse(
            request,
            "promotions.html",
            {
                "title": "Promociones",
                "active_nav": "promotions",
                "month": safe_month or month,
                "bank": bank,
                "category": category,
                "promo_type": promo_type,
                "quality": quality,
                "items": page_items,
                "total_items": len(cards),
                "page": max(1, page),
                "total_pages": total_pages,
                "banks": banks,
                "categories": audit.dataset.covered_categories,
                "promo_types": PROMO_TYPES,
                "quality_labels": QUALITY_LABELS,
                "error_message": error_message,
            },
        )

    @app.get("/ops", response_class=HTMLResponse)
    def ops_ui(request: Request, month: str | None = None) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "ops.html",
            {
                "title": "Operación",
                "active_nav": "ops",
                "default_month": month or now_month_ref(),
                "collect_result": None,
                "audit_result": None,
                "error_message": "",
                "banks": sorted([_bank_label(key) for key in SCRAPER_REGISTRY]),
                "admin_enabled": get_settings().enable_admin_endpoints,
                "collect_status": get_collect_job_status(),
            },
        )

    @app.post("/ops/collect", response_class=HTMLResponse)
    def ops_collect(
        request: Request,
        background_tasks: BackgroundTasks,
        month: str = Form(""),
        bank: str = Form(""),
    ) -> HTMLResponse:
        context = {
            "title": "Operación",
            "active_nav": "ops",
            "default_month": month or now_month_ref(),
            "collect_result": None,
            "audit_result": None,
            "error_message": "",
            "banks": sorted([_bank_label(key) for key in SCRAPER_REGISTRY]),
            "admin_enabled": get_settings().enable_admin_endpoints,
            "collect_status": get_collect_job_status(),
        }
        if not get_settings().enable_admin_endpoints:
            context["error_message"] = "Las operaciones web están deshabilitadas en este entorno."
            return templates.TemplateResponse(request, "ops.html", context, status_code=403)
        try:
            safe_month = validate_month(month)
            safe_bank = validate_bank(bank, set(SCRAPER_REGISTRY) | {"BNF", "Ueno", "Itau", "Sudameris", "Continental"}) if bank else None
            result = start_collect_job(background_tasks, month=safe_month or now_month_ref(), bank=safe_bank)
            context["collect_result"] = result
            context["collect_status"] = get_collect_job_status()
            context["default_month"] = safe_month or now_month_ref()
        except ValueError as exc:
            context["error_message"] = str(exc)
            return templates.TemplateResponse(request, "ops.html", context, status_code=400)
        except RuntimeError as exc:
            context["error_message"] = str(exc)
            context["collect_status"] = get_collect_job_status()
            return templates.TemplateResponse(request, "ops.html", context, status_code=409)
        except HTTPException as exc:
            context["error_message"] = str(exc.detail)
            context["collect_status"] = get_collect_job_status()
            return templates.TemplateResponse(request, "ops.html", context, status_code=exc.status_code)
        except Exception:
            context["error_message"] = "No se pudo ejecutar collect en este momento."
            context["collect_status"] = get_collect_job_status()
            return templates.TemplateResponse(request, "ops.html", context, status_code=500)
        return templates.TemplateResponse(request, "ops.html", context)

    @app.post("/ops/audit", response_class=HTMLResponse)
    def ops_audit(
        request: Request,
        month: str = Form(""),
        bank: str = Form(""),
        query: str = Form(""),
    ) -> HTMLResponse:
        context = {
            "title": "Operación",
            "active_nav": "ops",
            "default_month": month or now_month_ref(),
            "collect_result": None,
            "audit_result": None,
            "error_message": "",
            "banks": sorted([_bank_label(key) for key in SCRAPER_REGISTRY]),
            "admin_enabled": get_settings().enable_admin_endpoints,
            "collect_status": get_collect_job_status(),
        }
        if not get_settings().enable_admin_endpoints:
            context["error_message"] = "Las operaciones web están deshabilitadas en este entorno."
            return templates.TemplateResponse(request, "ops.html", context, status_code=403)
        try:
            safe_month = validate_month(month)
            safe_bank = validate_bank(bank, set(SCRAPER_REGISTRY) | {"BNF", "Ueno", "Itau", "Sudameris", "Continental"}) if bank else None
            result, elapsed = timed_call(
                build_audit_report,
                get_repository(),
                month_ref=safe_month,
                bank=safe_bank,
                queries=[query] if query.strip() else None,
            )
            context["audit_result"] = {"report": result, "elapsed_seconds": elapsed}
            context["default_month"] = safe_month or now_month_ref()
        except ValueError as exc:
            context["error_message"] = str(exc)
            return templates.TemplateResponse(request, "ops.html", context, status_code=400)
        except Exception:
            context["error_message"] = "No se pudo ejecutar audit en este momento."
            return templates.TemplateResponse(request, "ops.html", context, status_code=500)
        return templates.TemplateResponse(request, "ops.html", context)


def _bank_label(bank_key: str) -> str:
    if bank_key == "bnf":
        return "BNF"
    return bank_key.title()
