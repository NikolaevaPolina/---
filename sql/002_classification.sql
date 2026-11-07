ALTER TABLE meta.etl_runs
    ADD COLUMN IF NOT EXISTS model_seconds NUMERIC(12, 3),
    ADD COLUMN IF NOT EXISTS scored_count INTEGER NOT NULL DEFAULT 0;

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
);

CREATE TABLE IF NOT EXISTS gold.ticket_category_predictions (
    ticket_id BIGINT PRIMARY KEY REFERENCES silver.tickets(ticket_id),
    title TEXT NOT NULL,
    source_category TEXT NOT NULL,
    predicted_category TEXT NOT NULL,
    confidence NUMERIC(8, 4) NOT NULL,
    model_id UUID NOT NULL REFERENCES meta.model_versions(model_id),
    source_updated_at TIMESTAMPTZ NOT NULL,
    predicted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_ticket_predictions_category
    ON gold.ticket_category_predictions(predicted_category);
