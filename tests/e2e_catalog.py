"""Exercise the real services in a fresh Docker Compose project."""

import os
import subprocess
import time
from collections.abc import Callable
from typing import TypeVar

import httpx

T = TypeVar("T")


def wait_for(check: Callable[[], T | None], description: str) -> T:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if (result := check()) is not None:
            return result
        time.sleep(0.5)
    raise AssertionError(f"Timed out waiting for {description}")


def compose(*args: str) -> None:
    subprocess.run(["docker", "compose", *args], check=True)


def ready(client: httpx.Client) -> dict | None:
    try:
        response = client.get("/ready")
    except httpx.TransportError:
        return None
    return response.json() if response.status_code == 200 else None


def submit(client: httpx.Client) -> str:
    response = client.post("/sync/jobs")
    assert response.status_code == 202, response.text
    location = response.headers["Location"]
    assert location == f"/sync/jobs/{response.json()['task_id']}"
    return location


def wait_for_job(client: httpx.Client, location: str) -> dict:
    def terminal_status() -> dict | None:
        response = client.get(location)
        response.raise_for_status()
        job = response.json()
        return job if job["status"] in {"succeeded", "failed"} else None

    return wait_for(terminal_status, f"terminal status for {location}")


def test_catalog(client: httpx.Client, window_seconds: int) -> None:
    readiness = wait_for(lambda: ready(client), "Compose services")
    assert readiness["ready"]
    assert {"postgres", "rabbitmq", "redis"} <= readiness["services"].keys()
    assert client.get("/products").json() == []

    compose("stop", "worker")
    try:
        location = submit(client)
        assert client.get(location).json()["status"] == "queued"
    finally:
        compose("start", "worker")

    first = wait_for_job(client, location)
    assert (first["status"], first["processed"], first["error"]) == (
        "succeeded",
        2,
        None,
    )
    products = client.get("/products").json()
    assert [record["sku"] for record in products] == ["NOTE-01", "PEN-02"]
    print(
        "RabbitMQ delivered the job, and PostgreSQL contains two products.", flush=True
    )

    second = wait_for_job(client, submit(client))
    assert (second["status"], second["processed"]) == ("succeeded", 2)
    assert client.get("/products").json() == products
    print("Repeating the import did not duplicate the catalog.", flush=True)

    compose("stop", "supplier")
    try:
        failed = wait_for_job(client, submit(client))
        assert (failed["status"], failed["processed"], failed["error"]) == (
            "failed",
            None,
            "supplier_error",
        )
        assert client.get("/products").json() == products
        print("The failed job preserved the previous catalog.", flush=True)
    finally:
        compose("start", "supplier")

    limited = client.post("/sync/jobs")
    assert limited.status_code == 429, limited.text
    assert 1 <= int(limited.headers["Retry-After"]) <= window_seconds
    print("Redis enforced the rate limit and returned Retry-After.", flush=True)


if __name__ == "__main__":
    port = os.getenv("DEMO_API_PORT", "8000")
    window = int(os.environ["SYNC_JOB_RATE_WINDOW_SECONDS"])
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as api:
        test_catalog(api, window)
