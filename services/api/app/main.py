from __future__ import annotations

import json
import os
import sqlite3
from contextlib import asynccontextmanager, closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query

from .generator import build_ticket, resolve_ticket


DB_PATH = Path(os.getenv("SOURCE_DB_PATH", "/data/source.db"))
INITIAL_TICKETS = int(os.getenv("INITIAL_TICKETS", "1000"))


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize() -> None:
    with closing(connect()) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY,
                updated_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        count = connection.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        if count == 0:
            base_time = datetime.now(timezone.utc) - timedelta(minutes=10)
            rows = []
            for ticket_id in range(1, INITIAL_TICKETS + 1):
                ticket = build_ticket(ticket_id, base_time)
                rows.append((ticket_id, ticket["updated_at"], json.dumps(ticket, ensure_ascii=False)))
            connection.executemany(
                "INSERT INTO tickets(id, updated_at, payload) VALUES (?, ?, ?)", rows
            )
        connection.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize()
    yield


app = FastAPI(
    title="Mock Service Desk API",
    description="Автономный источник обезличенных обращений для макета платформы данных.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/tickets")
def get_tickets(
    updated_after: datetime | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    where = "WHERE updated_at > ?" if updated_after else ""
    parameters = [updated_after.astimezone(timezone.utc).isoformat()] if updated_after else []
    with closing(connect()) as connection:
        total = connection.execute(
            f"SELECT COUNT(*) FROM tickets {where}", parameters
        ).fetchone()[0]
        rows = connection.execute(
            f"SELECT payload FROM tickets {where} ORDER BY updated_at, id LIMIT ? OFFSET ?",
            [*parameters, limit, offset],
        ).fetchall()
    items = [json.loads(row["payload"]) for row in rows]
    next_offset = offset + len(items) if offset + len(items) < total else None
    return {"items": items, "total": total, "offset": offset, "next_offset": next_offset}


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: int) -> dict:
    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT payload FROM tickets WHERE id = ?", (ticket_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return json.loads(row["payload"])


@app.post("/admin/advance")
def advance_source(
    new_count: int = Query(default=100, ge=0, le=100_000),
    update_count: int = Query(default=20, ge=0, le=10_000),
) -> dict:
    """Add new tickets and resolve several open tickets to demonstrate CDC-like loading."""
    changed_at = datetime.now(timezone.utc)
    with closing(connect()) as connection:
        max_id = connection.execute("SELECT COALESCE(MAX(id), 0) FROM tickets").fetchone()[0]
        inserted = []
        for ticket_id in range(max_id + 1, max_id + new_count + 1):
            ticket = build_ticket(ticket_id, changed_at, force_open=ticket_id % 4 == 0)
            ticket["updated_at"] = (changed_at + timedelta(microseconds=ticket_id - max_id)).isoformat()
            inserted.append((ticket_id, ticket["updated_at"], json.dumps(ticket, ensure_ascii=False)))
        connection.executemany(
            "INSERT INTO tickets(id, updated_at, payload) VALUES (?, ?, ?)", inserted
        )

        candidates = connection.execute(
            "SELECT id, payload FROM tickets WHERE id <= ? ORDER BY id DESC LIMIT ?",
            (max_id, max(update_count * 10, 1)),
        ).fetchall()
        updated = 0
        for row in candidates:
            if updated >= update_count:
                break
            ticket = json.loads(row["payload"])
            if ticket["status"] not in {"Закрыта", "Решена"}:
                changed = changed_at + timedelta(milliseconds=updated + 1)
                ticket = resolve_ticket(ticket, changed)
                connection.execute(
                    "UPDATE tickets SET updated_at = ?, payload = ? WHERE id = ?",
                    (ticket["updated_at"], json.dumps(ticket, ensure_ascii=False), row["id"]),
                )
                updated += 1
        connection.commit()
    return {
        "status": "advanced",
        "new_tickets": len(inserted),
        "updated_tickets": updated,
        "changed_at": changed_at.isoformat(),
    }


@app.get("/stats")
def source_stats() -> dict:
    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count, MIN(updated_at) AS min_updated, MAX(updated_at) AS max_updated FROM tickets"
        ).fetchone()
    return dict(row)
