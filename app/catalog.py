from pydantic import BaseModel, ConfigDict, Field

from app.database import Database, Session


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


def upsert_products(session: Session, products: list[Product]) -> None:
    session.executemany(
        """
        INSERT INTO products (sku, name, price_cents) VALUES (%s, %s, %s)
        ON CONFLICT(sku) DO UPDATE SET
            name = excluded.name,
            price_cents = excluded.price_cents
        """,
        ((item.sku, item.name, item.price_cents) for item in products),
    )


class Catalog:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert(self, products: list[Product]) -> None:
        with self.database.transaction() as session:
            upsert_products(session, products)

    def list_products(self) -> list[Product]:
        with self.database.transaction() as session:
            rows = session.execute(
                "SELECT sku, name, price_cents FROM products ORDER BY sku"
            ).fetchall()
        return [
            Product(sku=sku, name=name, price_cents=price) for sku, name, price in rows
        ]
