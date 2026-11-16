import os
from hmac import compare_digest
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException

app = FastAPI(title="Demo Supplier API")


@app.get("/v1/products")
def list_products(
    authorization: Annotated[str | None, Header()] = None,
) -> list[dict[str, str | int]]:
    token = os.getenv("SUPPLIER_TOKEN")
    if token and not compare_digest(
        (authorization or "").encode(), f"Bearer {token}".encode()
    ):
        raise HTTPException(401, "Invalid bearer token", {"WWW-Authenticate": "Bearer"})

    return [
        {"code": "NOTE-01", "title": "Notebook", "amount": 750},
        {"code": "PEN-02", "title": "Gel pen", "amount": 225},
    ]
