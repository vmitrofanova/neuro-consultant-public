import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial

import httpx
import pika
import psycopg
import weaviate
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from redis import Redis
from redis.exceptions import RedisError
from weaviate.classes.init import AdditionalConfig, Timeout
from weaviate.exceptions import WeaviateBaseError


class DependencyUnavailable(Exception):
    pass


TIMEOUT = 3


def check_redis(url: str) -> None:
    with Redis.from_url(
        url, socket_connect_timeout=TIMEOUT, socket_timeout=TIMEOUT
    ) as client:
        if not client.ping():
            raise DependencyUnavailable


def connect_rabbitmq(url: str) -> pika.BlockingConnection:
    parameters = pika.URLParameters(url)
    parameters.socket_timeout = TIMEOUT
    parameters.stack_timeout = TIMEOUT
    parameters.blocked_connection_timeout = TIMEOUT
    return pika.BlockingConnection(parameters)


def check_rabbitmq(url: str) -> None:
    with connect_rabbitmq(url) as connection:
        connection.channel()


def check_mongodb(url: str) -> None:
    with MongoClient(url, timeoutMS=TIMEOUT * 1000) as client:
        client.admin.command("ping")


def check_postgres(url: str) -> None:
    with psycopg.connect(
        url, connect_timeout=TIMEOUT, options="-c statement_timeout=3000"
    ) as connection:
        connection.execute("SELECT 1").fetchone()


def check_weaviate(host: str, http_port: int, grpc_port: int) -> None:
    with weaviate.connect_to_local(
        host=host,
        port=http_port,
        grpc_port=grpc_port,
        additional_config=AdditionalConfig(timeout=Timeout(init=TIMEOUT)),
    ) as client:
        if not client.is_ready():
            raise DependencyUnavailable


def check_http(url: str) -> None:
    response = httpx.get(url, timeout=TIMEOUT)
    response.raise_for_status()


Check = Callable[[], None]


@dataclass(frozen=True)
class Dependency:
    name: str
    check: Check


def configured_dependencies() -> list[Dependency]:
    endpoints = (
        ("redis", "REDIS_URL", check_redis),
        ("rabbitmq", "RABBITMQ_URL", check_rabbitmq),
        ("mongodb", "MONGO_URI", check_mongodb),
        ("postgres", "POSTGRES_DSN", check_postgres),
        ("llm", "LLM_HEALTH_URL", check_http),
    )
    dependencies = [
        Dependency(name, partial(check, value))
        for name, variable, check in endpoints
        if (value := os.getenv(variable))
    ]
    if host := os.getenv("WEAVIATE_HOST"):
        dependencies.append(
            Dependency(
                "weaviate",
                partial(
                    check_weaviate,
                    host,
                    int(os.getenv("WEAVIATE_REST_PORT", "8080")),
                    int(os.getenv("WEAVIATE_GRPC_PORT", "50051")),
                ),
            )
        )
    return dependencies


def dependency_status(dependency: Dependency) -> tuple[str, str]:
    try:
        dependency.check()
    except (
        DependencyUnavailable,
        httpx.HTTPError,
        pika.exceptions.AMQPError,
        psycopg.Error,
        RedisError,
        PyMongoError,
        WeaviateBaseError,
        OSError,
    ):
        return dependency.name, "unavailable"
    return dependency.name, "ok"


def check_dependencies(dependencies: list[Dependency]) -> dict[str, str]:
    if not dependencies:
        return {}
    with ThreadPoolExecutor(max_workers=len(dependencies)) as pool:
        return dict(pool.map(dependency_status, dependencies))
