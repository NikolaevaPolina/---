from __future__ import annotations

import time

import psycopg

from .config import settings


def connect() -> psycopg.Connection:
    return psycopg.connect(settings.database_url)


def wait_for_database(attempts: int = 20, delay_seconds: float = 1.5) -> None:
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            with connect() as connection:
                connection.execute("SELECT 1")
                return
        except psycopg.Error as error:
            last_error = error
            time.sleep(delay_seconds)
    raise RuntimeError("PostgreSQL is unavailable") from last_error


def get_watermark(connection: psycopg.Connection):
    return connection.execute(
        "SELECT watermark FROM meta.etl_state WHERE pipeline_name = 'support_tickets'"
    ).fetchone()[0]


def set_watermark(connection: psycopg.Connection, watermark) -> None:
    connection.execute(
        """
        UPDATE meta.etl_state
        SET watermark = %s, updated_at = now()
        WHERE pipeline_name = 'support_tickets'
        """,
        (watermark,),
    )
