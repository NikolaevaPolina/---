from __future__ import annotations

from uuid import UUID

import psycopg


SILVER_COLUMNS = """
    ticket_id, title, description, category, service, priority, status,
    requester_department, assignee_group, assignee, created_at,
    first_response_at, resolved_at, closed_at, updated_at, sla_deadline,
    resolution_text, reopened_count, reaction_minutes, resolution_minutes,
    is_sla_breached, record_hash, source_batch_id
"""


def transform_silver(
    connection: psycopg.Connection, batch_id: UUID, mode: str
) -> int:
    source_filter = "" if mode == "full" else "WHERE batch_id = %(batch_id)s"
    query = f"""
        WITH latest AS (
            SELECT DISTINCT ON (source_ticket_id)
                source_ticket_id, payload, payload_hash, batch_id
            FROM bronze.tickets_raw
            {source_filter}
            ORDER BY source_ticket_id, source_updated_at DESC, raw_id DESC
        ), typed AS (
            SELECT
                source_ticket_id AS ticket_id,
                COALESCE(NULLIF(trim(payload->>'title'), ''), 'Без названия') AS title,
                COALESCE(payload->>'description', '') AS description,
                COALESCE(NULLIF(trim(payload->>'category'), ''), 'Не определена') AS category,
                COALESCE(NULLIF(trim(payload->>'service'), ''), 'Не определён') AS service,
                COALESCE(NULLIF(trim(payload->>'priority'), ''), 'Не определён') AS priority,
                COALESCE(NULLIF(trim(payload->>'status'), ''), 'Не определён') AS status,
                COALESCE(NULLIF(trim(payload->>'requester_department'), ''), 'Не определён') AS requester_department,
                COALESCE(NULLIF(trim(payload->>'assignee_group'), ''), 'Не назначена') AS assignee_group,
                NULLIF(trim(payload->>'assignee'), '') AS assignee,
                (payload->>'created_at')::timestamptz AS created_at,
                NULLIF(payload->>'first_response_at', '')::timestamptz AS first_response_at,
                NULLIF(payload->>'resolved_at', '')::timestamptz AS resolved_at,
                NULLIF(payload->>'closed_at', '')::timestamptz AS closed_at,
                (payload->>'updated_at')::timestamptz AS updated_at,
                (payload->>'sla_deadline')::timestamptz AS sla_deadline,
                NULLIF(trim(payload->>'resolution_text'), '') AS resolution_text,
                COALESCE((payload->>'reopened_count')::integer, 0) AS reopened_count,
                payload_hash AS record_hash,
                batch_id AS source_batch_id
            FROM latest
        )
        INSERT INTO silver.tickets ({SILVER_COLUMNS})
        SELECT
            ticket_id, title, description, category, service, priority, status,
            requester_department, assignee_group, assignee, created_at,
            first_response_at, resolved_at, closed_at, updated_at, sla_deadline,
            resolution_text, reopened_count,
            CASE WHEN first_response_at IS NOT NULL
                THEN round((extract(epoch FROM (first_response_at - created_at)) / 60.0)::numeric, 2)
            END AS reaction_minutes,
            CASE WHEN resolved_at IS NOT NULL
                THEN round((extract(epoch FROM (resolved_at - created_at)) / 60.0)::numeric, 2)
            END AS resolution_minutes,
            CASE
                WHEN resolved_at IS NOT NULL THEN resolved_at > sla_deadline
                ELSE now() > sla_deadline
            END AS is_sla_breached,
            record_hash, source_batch_id
        FROM typed
        WHERE true
        ON CONFLICT (ticket_id) DO UPDATE SET
            title = EXCLUDED.title,
            description = EXCLUDED.description,
            category = EXCLUDED.category,
            service = EXCLUDED.service,
            priority = EXCLUDED.priority,
            status = EXCLUDED.status,
            requester_department = EXCLUDED.requester_department,
            assignee_group = EXCLUDED.assignee_group,
            assignee = EXCLUDED.assignee,
            created_at = EXCLUDED.created_at,
            first_response_at = EXCLUDED.first_response_at,
            resolved_at = EXCLUDED.resolved_at,
            closed_at = EXCLUDED.closed_at,
            updated_at = EXCLUDED.updated_at,
            sla_deadline = EXCLUDED.sla_deadline,
            resolution_text = EXCLUDED.resolution_text,
            reopened_count = EXCLUDED.reopened_count,
            reaction_minutes = EXCLUDED.reaction_minutes,
            resolution_minutes = EXCLUDED.resolution_minutes,
            is_sla_breached = EXCLUDED.is_sla_breached,
            record_hash = EXCLUDED.record_hash,
            source_batch_id = EXCLUDED.source_batch_id,
            dw_updated_at = now()
        WHERE EXCLUDED.updated_at >= silver.tickets.updated_at
        RETURNING ticket_id
    """
    rows = connection.execute(query, {"batch_id": batch_id}).fetchall()
    return len(rows)


def _insert_requests_mart(connection: psycopg.Connection, date_filter: str = "") -> None:
    connection.execute(
        f"""
        INSERT INTO gold.mart_requests_daily
        SELECT
            created_at::date, service, category, priority, status, count(*)::integer
        FROM silver.tickets
        {date_filter}
        GROUP BY created_at::date, service, category, priority, status
        """
    )


def _insert_sla_mart(connection: psycopg.Connection, date_filter: str = "") -> None:
    connection.execute(
        f"""
        INSERT INTO gold.mart_sla_daily
        SELECT
            created_at::date,
            service,
            priority,
            count(*)::integer,
            count(*) FILTER (WHERE resolved_at IS NOT NULL)::integer,
            count(*) FILTER (WHERE is_sla_breached)::integer,
            round(count(*) FILTER (WHERE is_sla_breached)::numeric / NULLIF(count(*), 0), 4),
            round(avg(reaction_minutes), 2),
            round(avg(resolution_minutes), 2)
        FROM silver.tickets
        {date_filter}
        GROUP BY created_at::date, service, priority
        """
    )


def _insert_workload_mart(connection: psycopg.Connection, date_filter: str = "") -> None:
    connection.execute(
        f"""
        INSERT INTO gold.mart_workload_daily
        SELECT
            created_at::date,
            service,
            assignee_group,
            COALESCE(assignee, 'Не назначен'),
            count(*)::integer,
            count(*) FILTER (WHERE resolved_at IS NOT NULL)::integer,
            round(avg(resolution_minutes), 2),
            sum(reopened_count)::integer
        FROM silver.tickets
        {date_filter}
        GROUP BY created_at::date, service, assignee_group, COALESCE(assignee, 'Не назначен')
        """
    )


def refresh_gold(connection: psycopg.Connection, batch_id: UUID, mode: str) -> None:
    if mode == "full":
        connection.execute(
            "TRUNCATE gold.mart_requests_daily, gold.mart_sla_daily, gold.mart_workload_daily"
        )
        _insert_requests_mart(connection)
        _insert_sla_mart(connection)
        _insert_workload_mart(connection)
        return

    connection.execute(
        """
        CREATE TEMP TABLE affected_dates ON COMMIT DROP AS
        SELECT DISTINCT created_at::date AS report_date
        FROM silver.tickets
        WHERE source_batch_id = %s
        UNION
        SELECT DISTINCT created_at::date
        FROM silver.tickets
        WHERE resolved_at IS NULL
          AND is_sla_breached IS DISTINCT FROM (now() > sla_deadline)
        """,
        (batch_id,),
    )
    connection.execute(
        """
        UPDATE silver.tickets
        SET is_sla_breached = (now() > sla_deadline), dw_updated_at = now()
        WHERE resolved_at IS NULL
          AND is_sla_breached IS DISTINCT FROM (now() > sla_deadline)
        """
    )
    connection.execute(
        "DELETE FROM gold.mart_requests_daily WHERE report_date IN (SELECT report_date FROM affected_dates)"
    )
    connection.execute(
        "DELETE FROM gold.mart_sla_daily WHERE report_date IN (SELECT report_date FROM affected_dates)"
    )
    connection.execute(
        "DELETE FROM gold.mart_workload_daily WHERE report_date IN (SELECT report_date FROM affected_dates)"
    )
    date_filter = "WHERE created_at::date IN (SELECT report_date FROM affected_dates)"
    _insert_requests_mart(connection, date_filter)
    _insert_sla_mart(connection, date_filter)
    _insert_workload_mart(connection, date_filter)
