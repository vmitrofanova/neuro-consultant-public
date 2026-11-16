import os
from collections.abc import AsyncIterator
from contextlib import ExitStack, asynccontextmanager
from functools import partial
from uuid import UUID

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pika.exceptions import AMQPError
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel
from redis.exceptions import RedisError

from app.catalog import Catalog, Product
from app.database import Database
from app.infrastructure import (
    check_dependencies,
    configured_dependencies,
    connect_redis,
)
from app.jobs import Jobs, JobStatus, SyncJob
from app.queue import publish_sync
from app.rate_limit import SyncRateLimit
from app.supplier import (
    SupplierClient,
    SupplierError,
    SupplierTimeout,
    connect_supplier,
)


class SyncResult(BaseModel):
    processed: int


def create_app(*, supplier_transport: httpx.BaseTransport | None = None) -> FastAPI:
    database = Database()
    catalog = Catalog(database)
    jobs = Jobs(database)
    dependencies = configured_dependencies()
    queue_url = os.getenv("RABBITMQ_URL")
    redis_url = os.getenv("REDIS_URL")

    @asynccontextmanager
    async def lifespan(
        _: FastAPI,
    ) -> AsyncIterator[dict[str, SupplierClient | SyncRateLimit | None]]:
        jobs.initialize()
        with ExitStack() as resources:
            client = resources.enter_context(connect_supplier(supplier_transport))
            limiter = None
            if redis_url:
                limit = int(os.getenv("SYNC_JOB_RATE_LIMIT", "5"))
                window = int(os.getenv("SYNC_JOB_RATE_WINDOW_SECONDS", "60"))
                if limit < 1 or window < 1:
                    raise ValueError("Sync job rate limit and window must be positive")
                redis = resources.enter_context(connect_redis(redis_url))
                limiter = SyncRateLimit(redis, limit, window)
            yield {"supplier": SupplierClient(client), "sync_rate_limit": limiter}

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

    @app.post(
        "/sync/jobs",
        status_code=202,
        responses={
            202: {
                "headers": {"Location": {"schema": {"type": "string"}}},
            },
            429: {
                "description": "Sync job rate limit exceeded",
                "headers": {"Retry-After": {"schema": {"type": "integer"}}},
            },
            503: {"description": "Queue or rate limiter is unavailable"},
        },
    )
    def start_sync_job(request: Request, response: Response) -> SyncJob:
        if not queue_url:
            raise HTTPException(503, "Queue is not configured")
        if limiter := request.state.sync_rate_limit:
            client_host = request.client.host if request.client else "unknown"
            try:
                retry_after = limiter.retry_after(client_host)
            except RedisError as exc:
                raise HTTPException(503, "Rate limiter is unavailable") from exc
            if retry_after is not None:
                raise HTTPException(
                    429,
                    "Sync job rate limit exceeded",
                    headers={"Retry-After": str(retry_after)},
                )
        try:
            job = jobs.submit(partial(publish_sync, queue_url))
        except AMQPError as exc:
            raise HTTPException(503, "Queue is unavailable") from exc
        response.headers["Location"] = f"/sync/jobs/{job.task_id}"
        return job

    @app.get(
        "/sync/jobs/{task_id}", responses={404: {"description": "Sync job not found"}}
    )
    def get_sync_job(task_id: UUID) -> JobStatus:
        job = jobs.get(task_id)
        if job is None:
            raise HTTPException(404, "Sync job not found")
        return job

    return app
