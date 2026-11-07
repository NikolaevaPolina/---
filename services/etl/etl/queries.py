"""Запросы к слоям хранилища и служебным таблицам конвейера.

Значения передаются драйверу отдельно от текста SQL. Содержание заявок
не подставляется в запросы строковой операцией.
"""


class RunSQL:
    PING = "SELECT 1"
    GET_WATERMARK = """
        SELECT watermark FROM meta.etl_state WHERE pipeline_name = 'support_tickets'
    """
    SET_WATERMARK = """
        UPDATE meta.etl_state
        SET watermark = %s, updated_at = now()
        WHERE pipeline_name = 'support_tickets'
    """
    START = """
        INSERT INTO meta.etl_runs (run_id, mode, status, watermark_from)
        VALUES (%s, %s, 'running', %s)
    """
    SUCCESS = """
        UPDATE meta.etl_runs
        SET status = 'success', finished_at = now(), watermark_to = %s,
            extracted_count = %s, loaded_count = %s, processed_count = %s,
            duration_seconds = %s, extract_seconds = %s, load_seconds = %s,
            transform_seconds = %s, gold_seconds = %s,
            model_seconds = %s, scored_count = %s
        WHERE run_id = %s
    """
    FAILED_CHECK = """
        INSERT INTO meta.data_quality_checks
            (run_id, check_name, passed, actual_value, expected_value)
        VALUES (%s, %s, %s, %s, %s)
    """
    FAILURE = """
        UPDATE meta.etl_runs
        SET status = 'failed', finished_at = now(),
            extracted_count = %s, loaded_count = %s, processed_count = %s,
            duration_seconds = %s, error_message = %s
        WHERE run_id = %s
    """


class BronzeSQL:
    UPSERT = """
        INSERT INTO bronze.tickets_raw (
            source_ticket_id, source_updated_at, payload, payload_hash, batch_id
        )
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (source_ticket_id, payload_hash) DO UPDATE
        SET batch_id = EXCLUDED.batch_id,
            ingested_at = now(),
            source_updated_at = EXCLUDED.source_updated_at
    """


class SilverSQL:
    UPSERT = """
        WITH latest AS (
            SELECT DISTINCT ON (source_ticket_id)
                source_ticket_id, payload, payload_hash, batch_id
            FROM bronze.tickets_raw
            WHERE (%(full)s OR batch_id = %(batch_id)s)
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
        INSERT INTO silver.tickets (
            ticket_id, title, description, category, service, priority, status,
            requester_department, assignee_group, assignee, created_at,
            first_response_at, resolved_at, closed_at, updated_at, sla_deadline,
            resolution_text, reopened_count, reaction_minutes, resolution_minutes,
            is_sla_breached, record_hash, source_batch_id
        )
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


class GoldSQL:
    TRUNCATE = """
        TRUNCATE gold.mart_requests_daily, gold.mart_sla_daily, gold.mart_workload_daily
    """
    CREATE_AFFECTED_DATES = """
        CREATE TEMP TABLE affected_dates ON COMMIT DROP AS
        SELECT DISTINCT created_at::date AS report_date
        FROM silver.tickets
        WHERE source_batch_id = %s
        UNION
        SELECT DISTINCT created_at::date
        FROM silver.tickets
        WHERE resolved_at IS NULL
          AND is_sla_breached IS DISTINCT FROM (now() > sla_deadline)
    """
    UPDATE_OPEN_SLA = """
        UPDATE silver.tickets
        SET is_sla_breached = (now() > sla_deadline), dw_updated_at = now()
        WHERE resolved_at IS NULL
          AND is_sla_breached IS DISTINCT FROM (now() > sla_deadline)
    """
    DELETE_REQUESTS_AFFECTED = """
        DELETE FROM gold.mart_requests_daily
        WHERE report_date IN (SELECT report_date FROM affected_dates)
    """
    DELETE_SLA_AFFECTED = """
        DELETE FROM gold.mart_sla_daily
        WHERE report_date IN (SELECT report_date FROM affected_dates)
    """
    DELETE_WORKLOAD_AFFECTED = """
        DELETE FROM gold.mart_workload_daily
        WHERE report_date IN (SELECT report_date FROM affected_dates)
    """
    INSERT_REQUESTS_FULL = """
        INSERT INTO gold.mart_requests_daily
        SELECT created_at::date, service, category, priority, status, count(*)::integer
        FROM silver.tickets
        GROUP BY created_at::date, service, category, priority, status
    """
    INSERT_REQUESTS_AFFECTED = """
        INSERT INTO gold.mart_requests_daily
        SELECT created_at::date, service, category, priority, status, count(*)::integer
        FROM silver.tickets
        WHERE created_at::date IN (SELECT report_date FROM affected_dates)
        GROUP BY created_at::date, service, category, priority, status
    """
    INSERT_SLA_FULL = """
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
        GROUP BY created_at::date, service, priority
    """
    INSERT_SLA_AFFECTED = """
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
        WHERE created_at::date IN (SELECT report_date FROM affected_dates)
        GROUP BY created_at::date, service, priority
    """
    INSERT_WORKLOAD_FULL = """
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
        GROUP BY created_at::date, service, assignee_group, COALESCE(assignee, 'Не назначен')
    """
    INSERT_WORKLOAD_AFFECTED = """
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
        WHERE created_at::date IN (SELECT report_date FROM affected_dates)
        GROUP BY created_at::date, service, assignee_group, COALESCE(assignee, 'Не назначен')
    """


class QualitySQL:
    MISSING_TICKET_ID = "SELECT count(*) FROM silver.tickets WHERE ticket_id IS NULL"
    DUPLICATE_TICKET_ID = """
        SELECT count(*) - count(DISTINCT ticket_id) FROM silver.tickets
    """
    UPDATED_BEFORE_CREATED = """
        SELECT count(*) FROM silver.tickets WHERE updated_at < created_at
    """
    RESOLVED_BEFORE_CREATED = """
        SELECT count(*) FROM silver.tickets WHERE resolved_at < created_at
    """
    MISSING_DIMENSIONS = """
        SELECT count(*) FROM silver.tickets
        WHERE service = 'Не определён' OR category = 'Не определена'
           OR priority = 'Не определён' OR status = 'Не определён'
    """
    BRONZE_SILVER_BALANCE = """
        SELECT abs(
            (SELECT count(DISTINCT source_ticket_id) FROM bronze.tickets_raw) -
            (SELECT count(*) FROM silver.tickets)
        )
    """
    SAVE_RESULT = """
        INSERT INTO meta.data_quality_checks
            (run_id, check_name, passed, actual_value, expected_value)
        VALUES (%s, %s, %s, %s, %s)
    """


class ClassificationSQL:
    ALTER_RUNS = """
        ALTER TABLE meta.etl_runs
        ADD COLUMN IF NOT EXISTS model_seconds NUMERIC(12, 3),
        ADD COLUMN IF NOT EXISTS scored_count INTEGER NOT NULL DEFAULT 0
    """
    CREATE_MODEL_VERSIONS = """
        CREATE TABLE IF NOT EXISTS meta.model_versions (
            model_id UUID PRIMARY KEY,
            etl_run_id UUID NOT NULL REFERENCES meta.etl_runs(run_id),
            trained_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            model_name TEXT NOT NULL,
            training_count INTEGER NOT NULL,
            record_test_count INTEGER NOT NULL,
            record_accuracy NUMERIC(8, 4),
            record_macro_f1 NUMERIC(8, 4),
            template_test_count INTEGER NOT NULL,
            template_accuracy NUMERIC(8, 4),
            template_macro_f1 NUMERIC(8, 4),
            majority_baseline NUMERIC(8, 4),
            candidate_metrics JSONB NOT NULL,
            model_payload JSONB NOT NULL
        )
    """
    CREATE_PREDICTIONS = """
        CREATE TABLE IF NOT EXISTS gold.ticket_category_predictions (
            ticket_id BIGINT PRIMARY KEY REFERENCES silver.tickets(ticket_id),
            title TEXT NOT NULL,
            source_category TEXT NOT NULL,
            predicted_category TEXT NOT NULL,
            confidence NUMERIC(8, 4) NOT NULL,
            model_id UUID NOT NULL REFERENCES meta.model_versions(model_id),
            source_updated_at TIMESTAMPTZ NOT NULL,
            predicted_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """
    CREATE_PREDICTIONS_INDEX = """
        CREATE INDEX IF NOT EXISTS ix_ticket_predictions_category
        ON gold.ticket_category_predictions(predicted_category)
    """
    TRAINING_ROWS = """
        SELECT ticket_id, title, category FROM silver.tickets
        WHERE status IN ('Закрыта', 'Решена')
          AND category <> 'Не определена'
        ORDER BY ticket_id
    """
    SAVE_MODEL = """
        INSERT INTO meta.model_versions (
            model_id, etl_run_id, model_name, training_count, record_test_count,
            record_accuracy, record_macro_f1, template_test_count,
            template_accuracy, template_macro_f1, majority_baseline,
            candidate_metrics, model_payload
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    LATEST_MODEL = """
        SELECT model_id, model_name, model_payload FROM meta.model_versions
        ORDER BY trained_at DESC, model_id DESC LIMIT 1
    """
    DELETE_ALL_PREDICTIONS = "DELETE FROM gold.ticket_category_predictions"
    OPEN_TICKETS_FULL = """
        SELECT ticket_id, title, category, updated_at FROM silver.tickets
        WHERE status NOT IN ('Закрыта', 'Решена') ORDER BY ticket_id
    """
    DELETE_RESOLVED_PREDICTIONS = """
        DELETE FROM gold.ticket_category_predictions p
        USING silver.tickets s
        WHERE p.ticket_id = s.ticket_id AND s.source_batch_id = %s
          AND s.status IN ('Закрыта', 'Решена')
    """
    OPEN_TICKETS_BATCH = """
        SELECT ticket_id, title, category, updated_at FROM silver.tickets
        WHERE source_batch_id = %s
          AND status NOT IN ('Закрыта', 'Решена') ORDER BY ticket_id
    """
    UPSERT_PREDICTIONS = """
        INSERT INTO gold.ticket_category_predictions (
            ticket_id, title, source_category, predicted_category,
            confidence, model_id, source_updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (ticket_id) DO UPDATE SET
            title = EXCLUDED.title,
            source_category = EXCLUDED.source_category,
            predicted_category = EXCLUDED.predicted_category,
            confidence = EXCLUDED.confidence,
            model_id = EXCLUDED.model_id,
            source_updated_at = EXCLUDED.source_updated_at,
            predicted_at = now()
    """
