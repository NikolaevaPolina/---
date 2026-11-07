from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb


def canonical_hash(payload: dict) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def load_bronze(
    connection: psycopg.Connection, tickets: list[dict], batch_id: UUID
) -> int:
    rows = [
        (
            int(ticket["id"]),
            datetime.fromisoformat(ticket["updated_at"]),
            Jsonb(ticket),
            canonical_hash(ticket),
            batch_id,
        )
        for ticket in tickets
    ]
    if not rows:
        return 0
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO bronze.tickets_raw (
                source_ticket_id, source_updated_at, payload, payload_hash, batch_id
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (source_ticket_id, payload_hash) DO UPDATE
            SET batch_id = EXCLUDED.batch_id,
                ingested_at = now(),
                source_updated_at = EXCLUDED.source_updated_at
            """,
            rows,
        )
    return len(rows)
