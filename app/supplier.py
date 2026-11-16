import os

import httpx
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.catalog import Product


class SupplierError(Exception):
    pass


class SupplierTimeout(SupplierError):
    pass


class SupplierProduct(BaseModel):
    code: str
    title: str
    amount: int


supplier_payload = TypeAdapter(list[SupplierProduct])


def connect_supplier(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    token = os.getenv("SUPPLIER_TOKEN")
    return httpx.Client(
        base_url=os.getenv("SUPPLIER_URL", "http://127.0.0.1:8001"),
        headers={"Authorization": f"Bearer {token}"} if token else {},
        timeout=5.0,
        transport=transport,
    )


class SupplierClient:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def fetch_products(self) -> list[Product]:
        try:
            response = self.client.get("/v1/products")
            response.raise_for_status()
            records = supplier_payload.validate_json(response.content, strict=True)
            products = [
                Product(sku=row.code, name=row.title, price_cents=row.amount)
                for row in records
            ]
        except httpx.TimeoutException as exc:
            raise SupplierTimeout from exc
        except (httpx.HTTPError, ValidationError) as exc:
            raise SupplierError from exc

        if len({product.sku for product in products}) != len(products):
            raise SupplierError("Supplier returned duplicate product codes")
        return sorted(products, key=lambda product: product.sku)
