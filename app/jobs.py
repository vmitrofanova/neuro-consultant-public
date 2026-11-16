from collections.abc import Callable
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel

from app.catalog import CREATE_PRODUCTS, Product, upsert_products
from app.database import Database

Status = Literal["queued", "running", "succeeded", "failed"]
JobError = Literal["supplier_timeout", "supplier_error"]
CREATE_JOBS = """
    CREATE TABLE IF NOT EXISTS sync_jobs (
        task_id TEXT PRIMARY KEY NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
        processed INTEGER,
        error TEXT
    )
"""
INSERT_JOB = "INSERT INTO sync_jobs (task_id, status) VALUES (%s, 'queued')"


class SyncJob(BaseModel):
    task_id: UUID


class JobStatus(SyncJob):
    status: Status
    processed: int | None
    error: JobError | None


class Jobs:
    def __init__(self, database: Database) -> None:
        self.database = database

    def initialize(self) -> None:
        self.database.initialize(CREATE_PRODUCTS, CREATE_JOBS)

    def submit(self, publish: Callable[[SyncJob], None]) -> SyncJob:
        job = SyncJob(task_id=uuid4())
        with self.database.transaction() as session:
            session.lock_job(job.task_id)
            session.execute(INSERT_JOB, (str(job.task_id),))
            publish(job)
        return job

    def get(self, task_id: UUID) -> JobStatus | None:
        with self.database.transaction() as session:
            row = session.execute(
                "SELECT status, processed, error FROM sync_jobs WHERE task_id = %s",
                (str(task_id),),
            ).fetchone()
        if row is None:
            return None
        status, processed, error = row
        return JobStatus(
            task_id=task_id, status=status, processed=processed, error=error
        )

    def start(self, task_id: UUID, *, legacy: bool) -> Status | None:
        task_key = str(task_id)
        with self.database.transaction() as session:
            session.lock_job(task_id)
            if legacy:
                # Older publishers sent the same body before status rows existed.
                session.execute(INSERT_JOB + " ON CONFLICT DO NOTHING", (task_key,))
            if session.execute(
                """
                UPDATE sync_jobs SET status = 'running'
                WHERE task_id = %s AND status IN ('queued', 'running')
                """,
                (task_key,),
            ).rowcount:
                return "running"
            row = session.execute(
                "SELECT status FROM sync_jobs WHERE task_id = %s", (task_key,)
            ).fetchone()
            return row[0] if row else None

    def succeed(self, task_id: UUID, products: list[Product]) -> bool:
        with self.database.transaction() as session:
            updated = session.execute(
                """
                UPDATE sync_jobs SET status = 'succeeded', processed = %s
                WHERE task_id = %s AND status = 'running'
                """,
                (len(products), str(task_id)),
            ).rowcount
            if updated:
                upsert_products(session, products)
        return bool(updated)

    def fail(self, task_id: UUID, error: JobError) -> bool:
        with self.database.transaction() as session:
            updated = session.execute(
                """
                UPDATE sync_jobs SET status = 'failed', error = %s
                WHERE task_id = %s AND status = 'running'
                """,
                (error, str(task_id)),
            ).rowcount
            if updated:
                return True
            row = session.execute(
                "SELECT status FROM sync_jobs WHERE task_id = %s", (str(task_id),)
            ).fetchone()
            return row is not None and row[0] == "failed"
