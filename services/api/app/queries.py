"""Static, parameterized SQLite statements for the synthetic source."""


class TicketSQL:
    CREATE_TABLE = """
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY,
            updated_at TEXT NOT NULL,
            payload TEXT NOT NULL
        )
    """
    COUNT_ALL = "SELECT COUNT(*) FROM tickets"
    COUNT_UPDATED_AFTER = "SELECT COUNT(*) FROM tickets WHERE updated_at > ?"
    INSERT = "INSERT INTO tickets(id, updated_at, payload) VALUES (?, ?, ?)"
    PAGE_ALL = """
        SELECT payload FROM tickets
        ORDER BY updated_at, id LIMIT ? OFFSET ?
    """
    PAGE_UPDATED_AFTER = """
        SELECT payload FROM tickets WHERE updated_at > ?
        ORDER BY updated_at, id LIMIT ? OFFSET ?
    """
    GET_BY_ID = "SELECT payload FROM tickets WHERE id = ?"
    MAX_ID = "SELECT COALESCE(MAX(id), 0) FROM tickets"
    UPDATE_CANDIDATES = """
        SELECT id, payload FROM tickets
        WHERE id <= ? ORDER BY id DESC LIMIT ?
    """
    UPDATE_TICKET = "UPDATE tickets SET updated_at = ?, payload = ? WHERE id = ?"
    STATS = """
        SELECT COUNT(*) AS count,
               MIN(updated_at) AS min_updated,
               MAX(updated_at) AS max_updated
        FROM tickets
    """
