"""Запросы к данным для демонстрационного экрана специалиста."""


class OperatorSQL:
    ENSURE_SCHEMA = "CREATE SCHEMA IF NOT EXISTS demo"

    ENSURE_REVIEWS = """
        CREATE TABLE IF NOT EXISTS demo.reply_reviews (
            review_id BIGSERIAL PRIMARY KEY,
            ticket_id BIGINT NOT NULL REFERENCES silver.tickets(ticket_id),
            source_ticket_id BIGINT REFERENCES silver.tickets(ticket_id),
            model_id UUID,
            proposed_reply TEXT NOT NULL,
            edited_reply TEXT,
            decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
            review_note TEXT NOT NULL DEFAULT '',
            reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """

    LIST_OPEN = """
        SELECT s.ticket_id, s.title, s.description, s.service, s.status,
               s.priority, s.category, s.updated_at,
               p.predicted_category, p.confidence, p.model_id
        FROM silver.tickets AS s
        LEFT JOIN gold.ticket_category_predictions AS p
               ON p.ticket_id = s.ticket_id
        WHERE s.status NOT IN ('Закрыта', 'Решена')
        ORDER BY s.updated_at DESC, s.ticket_id DESC
        LIMIT %s
    """

    FIND_CLOSED = """
        SELECT ticket_id, title, description, service, category,
               resolution_text, updated_at
        FROM silver.tickets
        WHERE status IN ('Закрыта', 'Решена')
          AND NULLIF(BTRIM(resolution_text), '') IS NOT NULL
          AND (service = %s OR category = %s)
        ORDER BY updated_at DESC, ticket_id DESC
        LIMIT %s
    """

    INSERT_REVIEW = """
        INSERT INTO demo.reply_reviews (
            ticket_id, source_ticket_id, model_id, proposed_reply,
            edited_reply, decision, review_note
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING review_id
    """

    LIST_REVIEWS = """
        SELECT review_id, decision, source_ticket_id, reviewed_at, review_note
        FROM demo.reply_reviews
        WHERE ticket_id = %s
        ORDER BY reviewed_at DESC, review_id DESC
        LIMIT 10
    """
