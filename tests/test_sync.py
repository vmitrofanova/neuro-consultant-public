import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(autouse=True)
def configure_demo(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "catalog.sqlite3"))
    monkeypatch.setenv("SUPPLIER_URL", "https://supplier.example")
    monkeypatch.setenv("SUPPLIER_TOKEN", "test-token")


def test_sync_upserts_products_and_persists_them():
    records = [{"code": "PEN-02", "title": "Gel pen", "amount": 225}]

    def supplier(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url == "https://supplier.example/v1/products"
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(200, json=records)

    with TestClient(
        create_app(supplier_transport=httpx.MockTransport(supplier))
    ) as api:
        assert api.get("/health").json() == {"status": "ok"}
        assert api.get("/products").json() == []
        assert api.post("/sync").json() == {"processed": 1}
        records[0]["amount"] = 250
        assert api.post("/sync").json() == {"processed": 1}
        assert api.post("/sync").json() == {"processed": 1}

    with TestClient(create_app()) as restarted_api:
        assert restarted_api.get("/products").json() == [
            {"sku": "PEN-02", "name": "Gel pen", "price_cents": 250}
        ]


@pytest.mark.parametrize(
    "bad_response",
    [
        httpx.Response(503),
        httpx.Response(200, content=b"not json"),
        httpx.Response(
            200,
            json=[
                {"code": "PEN-02", "title": "Updated pen", "amount": 250},
                {"code": "NOTE-01", "title": "Notebook", "amount": -1},
            ],
        ),
        httpx.Response(
            200,
            json=[
                {"code": "PEN-02", "title": "Updated pen", "amount": 250},
                {"code": " PEN-02 ", "title": "Another pen", "amount": 275},
            ],
        ),
    ],
    ids=["upstream-error", "invalid-json", "invalid-product", "duplicate-code"],
)
def test_failed_import_preserves_catalog(bad_response):
    responses = iter(
        [
            httpx.Response(
                200, json=[{"code": "PEN-02", "title": "Gel pen", "amount": 225}]
            ),
            bad_response,
        ]
    )
    app = create_app(supplier_transport=httpx.MockTransport(lambda _: next(responses)))
    with TestClient(app) as api:
        assert api.post("/sync").status_code == 200
        assert api.post("/sync").status_code == 502
        assert api.get("/products").json() == [
            {"sku": "PEN-02", "name": "Gel pen", "price_cents": 225}
        ]


def test_supplier_timeout_returns_gateway_timeout():
    def supplier(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Demo timeout", request=request)

    with TestClient(
        create_app(supplier_transport=httpx.MockTransport(supplier))
    ) as api:
        assert api.post("/sync").status_code == 504
        assert api.get("/products").json() == []
