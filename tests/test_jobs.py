from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pika.exceptions import AMQPConnectionError

from app.catalog import Catalog, Product, upsert_products
from app.database import Database
from app.jobs import Jobs
from app.main import create_app


@pytest.fixture(autouse=True)
def use_temporary_database(monkeypatch, tmp_path):
    monkeypatch.delenv("POSTGRES_DSN", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "catalog.sqlite3"))


def test_failed_publication_rolls_back_job(monkeypatch):
    monkeypatch.setenv("RABBITMQ_URL", "amqp://localhost")
    attempted = []

    def unavailable_broker(_, job):
        attempted.append(job.task_id)
        raise AMQPConnectionError

    monkeypatch.setattr("app.main.publish_sync", unavailable_broker)
    with TestClient(create_app()) as api:
        assert api.post("/sync/jobs").status_code == 503
        assert len(attempted) == 1
        assert api.get(f"/sync/jobs/{attempted[0]}").status_code == 404


def test_worker_can_resume_running_job_and_ignores_completed_delivery():
    database = Database()
    jobs = Jobs(database)
    jobs.initialize()
    job = jobs.submit(lambda _: None)
    assert jobs.get(job.task_id).status == "queued"
    assert jobs.start(job.task_id, legacy=False) == "running"
    assert jobs.get(job.task_id).status == "running"
    # The worker reconnects after the first delivery was interrupted.
    assert jobs.start(job.task_id, legacy=False) == "running"

    product = Product(sku="PEN-02", name="Gel pen", price_cents=225)
    assert jobs.succeed(job.task_id, [product])
    assert jobs.start(job.task_id, legacy=False) == "succeeded"
    assert not jobs.succeed(
        job.task_id, [product.model_copy(update={"price_cents": 1})]
    )
    assert jobs.get(job.task_id).processed == 1
    assert Catalog(database).list_products() == [product]
    assert not jobs.fail(job.task_id, "supplier_error")


def test_catalog_and_success_status_are_committed_together(monkeypatch):
    database = Database()
    jobs = Jobs(database)
    jobs.initialize()
    job = jobs.submit(lambda _: None)
    jobs.start(job.task_id, legacy=False)
    product = Product(sku="PEN-02", name="Gel pen", price_cents=225)

    def write_then_fail(session, products):
        upsert_products(session, products)
        raise RuntimeError("injected write error")

    monkeypatch.setattr("app.jobs.upsert_products", write_then_fail)
    with pytest.raises(RuntimeError, match="injected write error"):
        jobs.succeed(job.task_id, [product])

    assert jobs.get(job.task_id).status == "running"
    assert Catalog(database).list_products() == []


def test_delivery_from_older_producer_can_create_status():
    jobs = Jobs(Database())
    jobs.initialize()
    task_id = uuid4()
    assert jobs.start(task_id, legacy=False) is None
    assert jobs.start(task_id, legacy=True) == "running"
    jobs.fail(task_id, "supplier_error")
    assert jobs.start(task_id, legacy=True) == "failed"
    assert jobs.get(task_id).error == "supplier_error"
