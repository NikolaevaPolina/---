from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from contextlib import asynccontextmanager, closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request

from .generator import build_ticket, resolve_ticket
from .queries import TicketSQL


DB_PATH = Path(os.getenv("SOURCE_DB_PATH", "/data/source.db"))
INITIAL_TICKETS = int(os.getenv("INITIAL_TICKETS", "1000"))
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("support-source")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize() -> None:
    with closing(connect()) as connection:
        connection.execute(TicketSQL.CREATE_TABLE)
        count = connection.execute(TicketSQL.COUNT_ALL).fetchone()[0]
        if count == 0:
            base_time = datetime.now(timezone.utc) - timedelta(minutes=10)
            rows = []
            for ticket_id in range(1, INITIAL_TICKETS + 1):
                ticket = build_ticket(ticket_id, base_time)
                rows.append((ticket_id, ticket["updated_at"], json.dumps(ticket, ensure_ascii=False)))
            connection.executemany(TicketSQL.INSERT, rows)
            count = len(rows)
        connection.commit()
    logger.info("source_initialized ticket_count=%d", count)


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


@app.middleware("http")
async def log_request(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as error:
        logger.error(
            "api_request_failed method=%s path=%s error_type=%s",
            request.method,
            request.url.path,
            type(error).__name__,
        )
        raise
    logger.info(
        "api_request method=%s path=%s status=%d duration_ms=%.1f",
        request.method,
        request.url.path,
        response.status_code,
        (time.perf_counter() - started) * 1000,
    )
    return response


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/tickets")
def get_tickets(
    updated_after: datetime | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    with closing(connect()) as connection:
        if updated_after:
            cursor = updated_after.astimezone(timezone.utc).isoformat()
            total = connection.execute(TicketSQL.COUNT_UPDATED_AFTER, (cursor,)).fetchone()[0]
            rows = connection.execute(
                TicketSQL.PAGE_UPDATED_AFTER, (cursor, limit, offset)
            ).fetchall()
        else:
            total = connection.execute(TicketSQL.COUNT_ALL).fetchone()[0]
            rows = connection.execute(TicketSQL.PAGE_ALL, (limit, offset)).fetchall()
    items = [json.loads(row["payload"]) for row in rows]
    next_offset = offset + len(items) if offset + len(items) < total else None
    return {"items": items, "total": total, "offset": offset, "next_offset": next_offset}


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: int) -> dict:
    with closing(connect()) as connection:
        row = connection.execute(TicketSQL.GET_BY_ID, (ticket_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return json.loads(row["payload"])


@app.post("/admin/advance")
def advance_source(
    new_count: int = Query(default=100, ge=0, le=100_000),
    update_count: int = Query(default=20, ge=0, le=10_000),
) -> dict:
    """Добавить заявки и завершить часть открытых для проверки выборочной загрузки."""
    changed_at = datetime.now(timezone.utc)
    with closing(connect()) as connection:
        max_id = connection.execute(TicketSQL.MAX_ID).fetchone()[0]
        inserted = []
        for ticket_id in range(max_id + 1, max_id + new_count + 1):
            ticket = build_ticket(ticket_id, changed_at, force_open=ticket_id % 4 == 0)
            ticket["updated_at"] = (changed_at + timedelta(microseconds=ticket_id - max_id)).isoformat()
            inserted.append((ticket_id, ticket["updated_at"], json.dumps(ticket, ensure_ascii=False)))
        connection.executemany(TicketSQL.INSERT, inserted)

        candidates = connection.execute(
            TicketSQL.UPDATE_CANDIDATES, (max_id, max(update_count * 10, 1))
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
                    TicketSQL.UPDATE_TICKET,
                    (ticket["updated_at"], json.dumps(ticket, ensure_ascii=False), row["id"]),
                )
                updated += 1
        connection.commit()
    logger.info("source_advanced new_tickets=%d updated_tickets=%d", len(inserted), updated)
    return {
        "status": "advanced",
        "new_tickets": len(inserted),
        "updated_tickets": updated,
        "changed_at": changed_at.isoformat(),
    }


@app.get("/stats")
def source_stats() -> dict:
    with closing(connect()) as connection:
        row = connection.execute(TicketSQL.STATS).fetchone()
    return dict(row)
