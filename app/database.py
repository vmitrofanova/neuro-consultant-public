import os
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from uuid import UUID

import psycopg


class Session:
    def __init__(self, cursor: sqlite3.Cursor | psycopg.Cursor, *, postgres: bool):
        self.cursor = cursor
        self.postgres = postgres

    def _statement(self, sql: str) -> str:
        return sql if self.postgres else sql.replace("%s", "?")

    def execute(
        self, sql: str, parameters: tuple = ()
    ) -> sqlite3.Cursor | psycopg.Cursor:
        self.cursor.execute(self._statement(sql), parameters)
        return self.cursor

    def executemany(self, sql: str, parameters: Iterable[tuple]) -> None:
        self.cursor.executemany(self._statement(sql), parameters)

    def lock_job(self, task_id: UUID) -> None:
        # SQLite serializes writes. With PostgreSQL, let a consumer wait for
        # the publisher's insert to commit before trying to update the row.
        if self.postgres:
            key = int.from_bytes(task_id.bytes[:8], "big", signed=True)
            self.execute("SELECT pg_advisory_xact_lock(%s)", (key,))


class Database:
    def __init__(self) -> None:
        self.dsn = os.getenv("POSTGRES_DSN")
        self.path = Path(os.getenv("DATABASE_PATH", "data/catalog.sqlite3"))

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        if self.dsn:
            with (
                psycopg.connect(self.dsn, connect_timeout=3) as connection,
                connection.cursor() as cursor,
            ):
                yield Session(cursor, postgres=True)
        else:
            with closing(sqlite3.connect(self.path)) as connection, connection:
                yield Session(connection.cursor(), postgres=False)

    def initialize(self, *statements: str) -> None:
        if not self.dsn:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as session:
            if session.postgres:
                session.execute("SELECT pg_advisory_xact_lock(73001)")
            for statement in statements:
                session.execute(statement)
