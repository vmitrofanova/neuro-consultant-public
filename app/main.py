import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pika.exceptions import AMQPError
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel

from app.catalog import Product, create_catalog
from app.infrastructure import check_dependencies, configured_dependencies
from app.queue import SyncJob, enqueue_sync
from app.supplier import (
    SupplierClient,
    SupplierError,
    SupplierTimeout,
    connect_supplier,
)


class SyncResult(BaseModel):
    processed: int


def create_app(*, supplier_transport: httpx.BaseTransport | None = None) -> FastAPI:
    catalog = create_catalog()
    dependencies = configured_dependencies()
    queue_url = os.getenv("RABBITMQ_URL")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[dict[str, SupplierClient]]:
        catalog.initialize()
        with connect_supplier(supplier_transport) as client:
            yield {"supplier": SupplierClient(client)}

    app = FastAPI(title="Catalog Sync API", lifespan=lifespan)
    Instrumentator().instrument(app).expose(app)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/system/healthcheck")
    def healthcheck() -> dict[str, str]:
        return {"message": "OK"}

    @app.get("/ready")
    def readiness() -> JSONResponse:
        services = check_dependencies(dependencies)
        ready = all(status == "ok" for status in services.values())
        return JSONResponse(
            {"ready": ready, "services": services}, 200 if ready else 503
        )

    @app.get("/products")
    def list_products() -> list[Product]:
        return catalog.list_products()

    @app.post("/sync", response_model=SyncResult)
    def sync_products(request: Request) -> SyncResult:
        try:
            products = request.state.supplier.fetch_products()
        except SupplierTimeout as exc:
            raise HTTPException(504, "Supplier timed out") from exc
        except SupplierError as exc:
            raise HTTPException(502, "Supplier response could not be imported") from exc
        catalog.upsert(products)
        return SyncResult(processed=len(products))

    @app.post("/sync/jobs", status_code=202)
    def start_sync_job() -> SyncJob:
        if not queue_url:
            raise HTTPException(503, "Queue is not configured")
        try:
            return enqueue_sync(queue_url)
        except AMQPError as exc:
            raise HTTPException(503, "Queue is unavailable") from exc

    return app
