CREATE SCHEMA IF NOT EXISTS meta;
CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;

CREATE TABLE IF NOT EXISTS meta.etl_runs (
    run_id UUID PRIMARY KEY,
    mode TEXT NOT NULL CHECK (mode IN ('full', 'incremental')),
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    watermark_from TIMESTAMPTZ,
    watermark_to TIMESTAMPTZ,
    extracted_count INTEGER NOT NULL DEFAULT 0,
    loaded_count INTEGER NOT NULL DEFAULT 0,
    processed_count INTEGER NOT NULL DEFAULT 0,
    duration_seconds NUMERIC(12, 3),
    extract_seconds NUMERIC(12, 3),
    load_seconds NUMERIC(12, 3),
    transform_seconds NUMERIC(12, 3),
    gold_seconds NUMERIC(12, 3),
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS meta.etl_state (
    pipeline_name TEXT PRIMARY KEY,
    watermark TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO meta.etl_state (pipeline_name, watermark)
VALUES ('support_tickets', NULL)
ON CONFLICT (pipeline_name) DO NOTHING;

CREATE TABLE IF NOT EXISTS meta.data_quality_checks (
    check_id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES meta.etl_runs(run_id),
    check_name TEXT NOT NULL,
    passed BOOLEAN NOT NULL,
    actual_value NUMERIC NOT NULL,
    expected_value TEXT NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bronze.tickets_raw (
    raw_id BIGSERIAL PRIMARY KEY,
    source_ticket_id BIGINT NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL,
    payload_hash TEXT NOT NULL,
    batch_id UUID NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_ticket_id, payload_hash)
);

CREATE INDEX IF NOT EXISTS ix_bronze_batch ON bronze.tickets_raw(batch_id);
CREATE INDEX IF NOT EXISTS ix_bronze_updated ON bronze.tickets_raw(source_updated_at);

CREATE TABLE IF NOT EXISTS silver.tickets (
    ticket_id BIGINT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    service TEXT NOT NULL,
    priority TEXT NOT NULL,
    status TEXT NOT NULL,
    requester_department TEXT NOT NULL,
    assignee_group TEXT NOT NULL,
    assignee TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    first_response_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL,
    sla_deadline TIMESTAMPTZ NOT NULL,
    resolution_text TEXT,
    reopened_count INTEGER NOT NULL DEFAULT 0,
    reaction_minutes NUMERIC(12, 2),
    resolution_minutes NUMERIC(12, 2),
    is_sla_breached BOOLEAN NOT NULL,
    record_hash TEXT NOT NULL,
    source_batch_id UUID NOT NULL,
    dw_updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_silver_created ON silver.tickets(created_at);
CREATE INDEX IF NOT EXISTS ix_silver_service ON silver.tickets(service);
CREATE INDEX IF NOT EXISTS ix_silver_assignee ON silver.tickets(assignee_group, assignee);

CREATE TABLE IF NOT EXISTS gold.mart_requests_daily (
    report_date DATE NOT NULL,
    service TEXT NOT NULL,
    category TEXT NOT NULL,
    priority TEXT NOT NULL,
    status TEXT NOT NULL,
    request_count INTEGER NOT NULL,
    PRIMARY KEY (report_date, service, category, priority, status)
);

CREATE TABLE IF NOT EXISTS gold.mart_sla_daily (
    report_date DATE NOT NULL,
    service TEXT NOT NULL,
    priority TEXT NOT NULL,
    request_count INTEGER NOT NULL,
    resolved_count INTEGER NOT NULL,
    breached_count INTEGER NOT NULL,
    breached_share NUMERIC(8, 4) NOT NULL,
    avg_reaction_minutes NUMERIC(12, 2),
    avg_resolution_minutes NUMERIC(12, 2),
    PRIMARY KEY (report_date, service, priority)
);

CREATE TABLE IF NOT EXISTS gold.mart_workload_daily (
    report_date DATE NOT NULL,
    service TEXT NOT NULL,
    assignee_group TEXT NOT NULL,
    assignee TEXT NOT NULL,
    assigned_count INTEGER NOT NULL,
    resolved_count INTEGER NOT NULL,
    avg_resolution_minutes NUMERIC(12, 2),
    reopened_count INTEGER NOT NULL,
    PRIMARY KEY (report_date, service, assignee_group, assignee)
);
