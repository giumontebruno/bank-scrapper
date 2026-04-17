from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import delete, insert, select

from core.config import get_settings
from db.connection import Database, create_database
from db.schema import fuel_prices as fuel_prices_table
from db.schema import promotions as promotions_table
from models.promotion import FuelPrice, Promotion
from utils.promo_dedupe import dedupe_promotions


class PromotionRepository:
    def __init__(self, database: str | Path | Database) -> None:
        self.database = self._coerce_database(database)

    @classmethod
    def default(cls) -> "PromotionRepository":
        return _default_repository(get_settings().database_url)

    @property
    def backend(self) -> str:
        return self.database.backend

    def save_promotions(self, promotions: list[Promotion]) -> None:
        promotions = dedupe_promotions(promotions)
        if not promotions:
            return
        rows = [self._promotion_row(item) for item in promotions]
        with self.database.engine.begin() as connection:
            connection.execute(insert(promotions_table), rows)

    def replace_promotions(self, bank: str, month_ref: str, promotions: list[Promotion]) -> None:
        promotions = dedupe_promotions(promotions)
        with self.database.engine.begin() as connection:
            # Estrategia explÃ­cita y portable: borramos solo el lote bank+month_ref
            # y luego insertamos el estado actual del scraper. Evita acumulaciÃ³n
            # entre reruns sin depender de una clave lÃ³gica frÃ¡gil por promo.
            connection.execute(
                delete(promotions_table).where(
                    promotions_table.c.bank == bank,
                    promotions_table.c.month_ref == month_ref,
                )
            )
            if promotions:
                connection.execute(insert(promotions_table), [self._promotion_row(item) for item in promotions])

    def list_promotions(
        self,
        *,
        month_ref: str | None = None,
        bank: str | None = None,
        category: str | None = None,
        limit: int | None = None,
    ) -> list[Promotion]:
        statement = select(promotions_table.c.payload).order_by(promotions_table.c.id.desc())
        if month_ref:
            statement = statement.where(promotions_table.c.month_ref == month_ref)
        if limit:
            statement = statement.limit(limit)
        with self.database.engine.begin() as connection:
            rows = connection.execute(statement).fetchall()
        promotions = [Promotion.parse_obj(json.loads(row.payload)) for row in rows]
        if bank:
            promotions = [item for item in promotions if item.bank.lower() == bank.lower()]
        if category:
            promotions = [item for item in promotions if item.category == category]
        return promotions

    def list_banks(self, *, month_ref: str | None = None) -> dict[str, int]:
        counts: dict[str, int] = {}
        for promotion in self.list_promotions(month_ref=month_ref):
            counts[promotion.bank] = counts.get(promotion.bank, 0) + 1
        return dict(sorted(counts.items()))

    def save_fuel_prices(self, prices: list[FuelPrice]) -> None:
        with self.database.engine.begin() as connection:
            connection.execute(delete(fuel_prices_table))
            if prices:
                connection.execute(insert(fuel_prices_table), [self._fuel_price_row(item) for item in prices])

    def list_fuel_prices(self, *, month_ref: str | None = None) -> list[FuelPrice]:
        statement = select(
            fuel_prices_table.c.brand,
            fuel_prices_table.c.octane,
            fuel_prices_table.c.base_price,
            fuel_prices_table.c.captured_at,
            fuel_prices_table.c.source_url,
            fuel_prices_table.c.raw_text,
        ).order_by(fuel_prices_table.c.octane.asc(), fuel_prices_table.c.brand.asc())
        with self.database.engine.begin() as connection:
            rows = connection.execute(statement).fetchall()
        prices = [
            FuelPrice(
                brand=row.brand,
                octane=row.octane,
                base_price=row.base_price,
                captured_at=row.captured_at,
                source_url=row.source_url,
                raw_text=row.raw_text,
            )
            for row in rows
        ]
        if month_ref:
            return [item for item in prices if item.captured_at.startswith(month_ref)]
        return prices

    def _coerce_database(self, value: str | Path | Database) -> Database:
        if isinstance(value, Database):
            value.initialize()
            return value
        if isinstance(value, Path):
            return create_database(value.as_posix())
        return create_database(value)

    def _promotion_row(self, promotion: Promotion) -> dict[str, Any]:
        return {
            "bank": promotion.bank,
            "month_ref": promotion.month_ref,
            "source_url": promotion.source_url,
            "payload": promotion.json(),
        }

    def _fuel_price_row(self, item: FuelPrice) -> dict[str, Any]:
        return {
            "brand": item.brand,
            "octane": item.octane,
            "base_price": item.base_price,
            "captured_at": item.captured_at,
            "source_url": item.source_url,
            "raw_text": item.raw_text,
        }


@lru_cache(maxsize=4)
def _default_repository(database_url: str) -> PromotionRepository:
    return PromotionRepository(database_url)


def reset_repository_cache() -> None:
    _default_repository.cache_clear()
