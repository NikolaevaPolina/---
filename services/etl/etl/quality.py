from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

import psycopg

from .queries import QualitySQL


@dataclass(frozen=True)
class Check:
    name: str
    query: str
    expected: str
    is_passed: callable


CHECKS = [
    Check("silver_missing_ticket_id", QualitySQL.MISSING_TICKET_ID, "0", lambda v: v == 0),
    Check("silver_duplicate_ticket_id", QualitySQL.DUPLICATE_TICKET_ID, "0", lambda v: v == 0),
    Check("updated_before_created", QualitySQL.UPDATED_BEFORE_CREATED, "0", lambda v: v == 0),
    Check("resolved_before_created", QualitySQL.RESOLVED_BEFORE_CREATED, "0", lambda v: v == 0),
    Check(
        "missing_dimensions",
        QualitySQL.MISSING_DIMENSIONS,
        "0",
        lambda v: v == 0,
    ),
    Check(
        "bronze_silver_balance",
        QualitySQL.BRONZE_SILVER_BALANCE,
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
        connection.execute(QualitySQL.SAVE_RESULT, (run_id, check.name, passed, numeric_value, check.expected))
        results.append({"check": check.name, "passed": passed, "actual": str(value)})
    return results
