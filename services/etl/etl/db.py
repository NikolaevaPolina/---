from __future__ import annotations

import time

import psycopg

from .config import settings
from .queries import RunSQL


def connect() -> psycopg.Connection:
    return psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
    )


def wait_for_database(attempts: int = 20, delay_seconds: float = 1.5) -> None:
    for _ in range(attempts):
        try:
            with connect() as connection:
                connection.execute(RunSQL.PING)
                return
        except psycopg.Error:
            time.sleep(delay_seconds)
    raise RuntimeError("PostgreSQL is unavailable; check local database settings") from None


def get_watermark(connection: psycopg.Connection):
    return connection.execute(RunSQL.GET_WATERMARK).fetchone()[0]


def set_watermark(connection: psycopg.Connection, watermark) -> None:
    connection.execute(RunSQL.SET_WATERMARK, (watermark,))
