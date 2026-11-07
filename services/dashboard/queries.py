"""Static, parameterized SQL for the analytical dashboard."""


class DashboardSQL:
    DATE_BOUNDS = """
        SELECT min(report_date) AS min_date, max(report_date) AS max_date
        FROM gold.mart_requests_daily
    """
    SERVICES = """
        SELECT DISTINCT service FROM gold.mart_requests_daily ORDER BY service
    """
    OVERVIEW = """
        SELECT
            sum(request_count)::integer AS requests,
            sum(resolved_count)::integer AS resolved,
            sum(breached_count)::integer AS breached,
            round(sum(breached_count)::numeric / NULLIF(sum(request_count), 0) * 100, 1)
                AS breached_pct,
            round(sum(avg_resolution_minutes * resolved_count) /
                  NULLIF(sum(resolved_count), 0), 1) AS avg_resolution
        FROM gold.mart_sla_daily
        WHERE report_date BETWEEN :date_from AND :date_to
          AND service = ANY(:services)
    """
    DAILY = """
        SELECT report_date, service, sum(request_count)::integer AS request_count
        FROM gold.mart_requests_daily
        WHERE report_date BETWEEN :date_from AND :date_to AND service = ANY(:services)
        GROUP BY report_date, service ORDER BY report_date, service
    """
    BY_CATEGORY = """
        SELECT category, sum(request_count)::integer AS request_count
        FROM gold.mart_requests_daily
        WHERE report_date BETWEEN :date_from AND :date_to AND service = ANY(:services)
        GROUP BY category ORDER BY request_count DESC
    """
    BY_PRIORITY = """
        SELECT priority, sum(request_count)::integer AS request_count
        FROM gold.mart_requests_daily
        WHERE report_date BETWEEN :date_from AND :date_to AND service = ANY(:services)
        GROUP BY priority ORDER BY request_count DESC
    """
    SLA_DAILY = """
        SELECT report_date,
               round(sum(breached_count)::numeric / NULLIF(sum(request_count), 0) * 100, 1)
                   AS breached_pct,
               round(sum(avg_resolution_minutes * resolved_count) /
                     NULLIF(sum(resolved_count), 0), 1) AS avg_resolution_minutes
        FROM gold.mart_sla_daily
        WHERE report_date BETWEEN :date_from AND :date_to AND service = ANY(:services)
        GROUP BY report_date ORDER BY report_date
    """
    WORKLOAD = """
        SELECT assignee_group, assignee,
               sum(assigned_count)::integer AS assigned_count,
               sum(resolved_count)::integer AS resolved_count,
               round(sum(avg_resolution_minutes * resolved_count) /
                     NULLIF(sum(resolved_count), 0), 1) AS avg_resolution_minutes,
               sum(reopened_count)::integer AS reopened_count
        FROM gold.mart_workload_daily
        WHERE report_date BETWEEN :date_from AND :date_to AND service = ANY(:services)
        GROUP BY assignee_group, assignee ORDER BY assigned_count DESC
    """
    MODEL_VERSIONS = """
        SELECT model_id::text, model_name, trained_at, training_count,
               record_test_count, record_accuracy, record_macro_f1,
               template_test_count, template_accuracy, template_macro_f1,
               majority_baseline, candidate_metrics
        FROM meta.model_versions ORDER BY trained_at DESC LIMIT 1
    """
    PREDICTIONS = """
        SELECT p.ticket_id, p.title, p.source_category,
               p.predicted_category, p.confidence, s.service
        FROM gold.ticket_category_predictions p
        JOIN silver.tickets s ON s.ticket_id = p.ticket_id
        WHERE s.created_at::date BETWEEN :date_from AND :date_to
          AND s.service = ANY(:services)
        ORDER BY p.predicted_at DESC LIMIT 200
    """
    RUNS = """
        SELECT run_id::text, mode, status, started_at, finished_at,
               extracted_count, processed_count, duration_seconds,
               extract_seconds, load_seconds, transform_seconds, gold_seconds,
               model_seconds, scored_count
        FROM meta.etl_runs ORDER BY started_at DESC LIMIT 20
    """
    CHECKS = """
        SELECT c.checked_at, c.check_name, c.passed, c.actual_value, c.expected_value
        FROM meta.data_quality_checks c
        ORDER BY c.checked_at DESC LIMIT 50
    """
