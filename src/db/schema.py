from __future__ import annotations

from sqlalchemy import Column, Float, Index, Integer, MetaData, Table, Text

metadata = MetaData()

promotions = Table(
    "promotions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("bank", Text),
    Column("month_ref", Text),
    Column("source_url", Text),
    Column("payload", Text, nullable=False),
    Index("ix_promotions_bank_month_ref", "bank", "month_ref"),
)

fuel_prices = Table(
    "fuel_prices",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("brand", Text, nullable=False),
    Column("octane", Integer, nullable=False),
    Column("base_price", Float, nullable=False),
    Column("captured_at", Text, nullable=False),
    Column("source_url", Text, nullable=False),
    Column("raw_text", Text),
    Index("ix_fuel_prices_brand_octane", "brand", "octane"),
)
