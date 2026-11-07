from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

import psycopg


@dataclass(frozen=True)
class Check:
    name: str
    query: str
    expected: str
    is_passed: callable


CHECKS = [
    Check("silver_missing_ticket_id", "SELECT count(*) FROM silver.tickets WHERE ticket_id IS NULL", "0", lambda v: v == 0),
    Check("silver_duplicate_ticket_id", "SELECT count(*) - count(DISTINCT ticket_id) FROM silver.tickets", "0", lambda v: v == 0),
    Check("updated_before_created", "SELECT count(*) FROM silver.tickets WHERE updated_at < created_at", "0", lambda v: v == 0),
    Check("resolved_before_created", "SELECT count(*) FROM silver.tickets WHERE resolved_at < created_at", "0", lambda v: v == 0),
    Check(
        "missing_dimensions",
        """SELECT count(*) FROM silver.tickets
           WHERE service = 'Не определён' OR category = 'Не определена'
              OR priority = 'Не определён' OR status = 'Не определён'""",
        "0",
        lambda v: v == 0,
    ),
    Check(
        "bronze_silver_balance",
        """SELECT abs(
             (SELECT count(DISTINCT source_ticket_id) FROM bronze.tickets_raw) -
             (SELECT count(*) FROM silver.tickets)
           )""",
        "0",
        lambda v: v == 0,
    ),
]


def run_quality_checks(connection: psycopg.Connection, run_id: UUID) -> list[dict]:
    results = []
    for check in CHECKS:
        value = connection.execute(check.query).fetchone()[0]
        numeric_value = Decimal(str(value))
        passed = bool(check.is_passed(value))
        connection.execute(
            """
            INSERT INTO meta.data_quality_checks
                (run_id, check_name, passed, actual_value, expected_value)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (run_id, check.name, passed, numeric_value, check.expected),
        )
        results.append({"check": check.name, "passed": passed, "actual": str(value)})
    return results
