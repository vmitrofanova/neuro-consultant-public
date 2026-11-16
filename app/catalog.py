import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Protocol

import psycopg
from pydantic import BaseModel, ConfigDict, Field


class Product(BaseModel):
    model_config = ConfigDict(strict=True, str_strip_whitespace=True)

    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    price_cents: int = Field(ge=0, le=2**63 - 1)


CREATE_PRODUCTS = """
    CREATE TABLE IF NOT EXISTS products (
        sku TEXT PRIMARY KEY NOT NULL,
        name TEXT NOT NULL,
        price_cents BIGINT NOT NULL CHECK (price_cents >= 0)
    )
"""
SELECT_PRODUCTS = "SELECT sku, name, price_cents FROM products ORDER BY sku"


class Catalog(Protocol):
    def initialize(self) -> None: ...

    def upsert(self, products: list[Product]) -> None: ...

    def list_products(self) -> list[Product]: ...


class SqliteCatalog:
    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(CREATE_PRODUCTS)

    def upsert(self, products: list[Product]) -> None:
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.executemany(
                """
                    INSERT INTO products (sku, name, price_cents) VALUES (?, ?, ?)
                    ON CONFLICT(sku) DO UPDATE SET
                        name = excluded.name,
                        price_cents = excluded.price_cents
                    """,
                ((item.sku, item.name, item.price_cents) for item in products),
            )

    def list_products(self) -> list[Product]:
        with closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute(SELECT_PRODUCTS).fetchall()
        return [
            Product(sku=sku, name=name, price_cents=price) for sku, name, price in rows
        ]


class PostgresCatalog:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def initialize(self) -> None:
        with psycopg.connect(self.dsn, connect_timeout=3) as connection:
            # API and worker may initialize the same schema at startup.
            connection.execute("SELECT pg_advisory_xact_lock(73001)")
            connection.execute(CREATE_PRODUCTS)

    def upsert(self, products: list[Product]) -> None:
        with (
            psycopg.connect(self.dsn, connect_timeout=3) as connection,
            connection.cursor() as cursor,
        ):
            cursor.executemany(
                """
                INSERT INTO products (sku, name, price_cents) VALUES (%s, %s, %s)
                ON CONFLICT(sku) DO UPDATE SET
                    name = excluded.name,
                    price_cents = excluded.price_cents
                """,
                ((item.sku, item.name, item.price_cents) for item in products),
            )

    def list_products(self) -> list[Product]:
        with psycopg.connect(self.dsn, connect_timeout=3) as connection:
            rows = connection.execute(SELECT_PRODUCTS).fetchall()
        return [
            Product(sku=sku, name=name, price_cents=price) for sku, name, price in rows
        ]


def create_catalog() -> Catalog:
    if dsn := os.getenv("POSTGRES_DSN"):
        return PostgresCatalog(dsn)
    return SqliteCatalog(Path(os.getenv("DATABASE_PATH", "data/catalog.sqlite3")))
