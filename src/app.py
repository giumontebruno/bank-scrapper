from __future__ import annotations

import json

import typer

from core.collect import run_collect
from core.config import get_settings
from exporters.output import export_promotions
from query.audit import build_audit_report, render_audit_report
from query.engine import QueryEngine
from query.repository import PromotionRepository

cli = typer.Typer(help="CLI de promo-query-py")


@cli.command()
def collect(month: str = typer.Option(..., "--month"), bank: str | None = typer.Option(None, "--bank")) -> None:
    """Recolecta combustibles y promociones bancarias."""
    repository = PromotionRepository.default()
    try:
        payload = run_collect(repository, month=month, bank=bank)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@cli.command()
def query(text: str = typer.Option(..., "--text")) -> None:
    engine = QueryEngine(PromotionRepository.default())
    typer.echo(json.dumps(engine.query(text), ensure_ascii=False, indent=2))


@cli.command()
def export(format: str = typer.Option(..., "--format")) -> None:
    path = export_promotions(PromotionRepository.default(), format)
    typer.echo(str(path))


@cli.command()
def audit(
    month: str | None = typer.Option(None, "--month"),
    bank: str | None = typer.Option(None, "--bank"),
    query: list[str] | None = typer.Option(None, "--query"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    report = build_audit_report(
        PromotionRepository.default(),
        month_ref=month,
        bank=bank,
        queries=list(query or []),
    )
    if json_output:
        typer.echo(json.dumps(report.dict(), ensure_ascii=False, indent=2))
        return
    typer.echo(render_audit_report(report))


@cli.command("config")
def show_config() -> None:
    settings = get_settings()
    typer.echo(
        json.dumps(
            {
                "app_env": settings.app_env,
                "database_url": settings.database_url,
                "api_host": settings.api_host,
                "api_port": settings.api_port,
                "log_level": settings.log_level,
                "enable_admin_endpoints": settings.enable_admin_endpoints,
                "cors_origins": settings.cors_origins,
                "bank_sources_path": str(settings.bank_sources_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    cli()
