"""Доступ к базе данных из демонстрационного экрана специалиста."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.rows import dict_row

from queries import OperatorSQL


@dataclass(frozen=True)
class DatabaseSettings:
    host: str
    port: int
    dbname: str
    user: str
    password: str = field(repr=False)

    @classmethod
    def from_environment(cls) -> "DatabaseSettings":
        names = (
            "POSTGRES_HOST",
            "POSTGRES_PORT",
            "POSTGRES_DB",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
        )
        values = {name: os.environ.get(name, "") for name in names}
        if any(not value for value in values.values()):
            raise RuntimeError("Database configuration is incomplete")
        try:
            port = int(values["POSTGRES_PORT"])
        except ValueError as error:
            raise RuntimeError("Database configuration is invalid") from error
        return cls(
            host=values["POSTGRES_HOST"],
            port=port,
            dbname=values["POSTGRES_DB"],
            user=values["POSTGRES_USER"],
            password=values["POSTGRES_PASSWORD"],
        )


class OperatorRepository:
    def __init__(self, settings: DatabaseSettings):
        self.settings = settings

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(
            host=self.settings.host,
            port=self.settings.port,
            dbname=self.settings.dbname,
            user=self.settings.user,
            password=self.settings.password,
            connect_timeout=5,
            row_factory=dict_row,
        )

    def prepare(self) -> None:
        with self._connect() as connection:
            connection.execute(OperatorSQL.ENSURE_SCHEMA)
            connection.execute(OperatorSQL.ENSURE_REVIEWS)

    def open_tickets(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return connection.execute(OperatorSQL.LIST_OPEN, (limit,)).fetchall()

    def closed_candidates(
        self, service: str, category: str, limit: int = 500
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return connection.execute(
                OperatorSQL.FIND_CLOSED, (service, category, limit)
            ).fetchall()

    def save_review(
        self,
        *,
        ticket_id: int,
        source_ticket_id: int | None,
        model_id: Any,
        proposed_reply: str,
        edited_reply: str,
        decision: str,
        review_note: str,
    ) -> int:
        if decision not in {"approved", "rejected"}:
            raise ValueError("Invalid review decision")
        if decision == "approved" and not edited_reply.strip():
            raise ValueError("An approved reply cannot be empty")
        with self._connect() as connection:
            row = connection.execute(
                OperatorSQL.INSERT_REVIEW,
                (
                    ticket_id,
                    source_ticket_id,
                    model_id,
                    proposed_reply,
                    edited_reply.strip() or None,
                    decision,
                    review_note.strip(),
                ),
            ).fetchone()
            return int(row["review_id"])

    def reviews(self, ticket_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return connection.execute(OperatorSQL.LIST_REVIEWS, (ticket_id,)).fetchall()
