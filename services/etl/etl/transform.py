"""Move ticket versions into the typed layer and refresh analytical marts."""

from __future__ import annotations

from uuid import UUID

import psycopg

from .queries import GoldSQL, SilverSQL


def transform_silver(
    connection: psycopg.Connection, batch_id: UUID, mode: str
) -> int:
    rows = connection.execute(
        SilverSQL.UPSERT,
        {"batch_id": batch_id, "full": mode == "full"},
    ).fetchall()
    return len(rows)


def refresh_gold(connection: psycopg.Connection, batch_id: UUID, mode: str) -> int:
    if mode == "full":
        connection.execute(GoldSQL.TRUNCATE)
        return sum(
            connection.execute(query).rowcount
            for query in (
                GoldSQL.INSERT_REQUESTS_FULL,
                GoldSQL.INSERT_SLA_FULL,
                GoldSQL.INSERT_WORKLOAD_FULL,
            )
        )

    connection.execute(GoldSQL.CREATE_AFFECTED_DATES, (batch_id,))
    connection.execute(GoldSQL.UPDATE_OPEN_SLA)
    connection.execute(GoldSQL.DELETE_REQUESTS_AFFECTED)
    connection.execute(GoldSQL.DELETE_SLA_AFFECTED)
    connection.execute(GoldSQL.DELETE_WORKLOAD_AFFECTED)
    return sum(
        connection.execute(query).rowcount
        for query in (
            GoldSQL.INSERT_REQUESTS_AFFECTED,
            GoldSQL.INSERT_SLA_AFFECTED,
            GoldSQL.INSERT_WORKLOAD_AFFECTED,
        )
    )
