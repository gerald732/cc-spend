"""SQLite persistence layer for cc-spend transactions."""

import sqlite3
from datetime import datetime
import config

DB_PATH = config.DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    merchant    TEXT NOT NULL,
    amount      REAL NOT NULL,
    card_type   TEXT NOT NULL,
    category    TEXT NOT NULL
);
"""


def _connect():
    """Open a connection to the configured SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the transactions table if it does not already exist."""
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def insert_transaction(
    timestamp: str, merchant: str, amount: float, card_type: str, category: str
):
    """Insert a single transaction row."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO transactions "
            "(timestamp, merchant, amount, card_type, category) "
            "VALUES (?, ?, ?, ?, ?)",
            (timestamp, merchant, amount, card_type, category),
        )


def get_period_total(card_type: str, period_start: datetime) -> float:
    """Return the total amount spent on card_type from period_start to now."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions "
            "WHERE card_type = ? AND timestamp >= ?",
            (card_type, period_start.isoformat()),
        ).fetchone()
    return row[0]


def get_monthly_category_total(card_type: str, category: str, period_start: datetime) -> float:
    """Return the total for a specific card + category from period_start to now."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions "
            "WHERE card_type = ? AND category = ? AND timestamp >= ?",
            (card_type, category, period_start.isoformat()),
        ).fetchone()
    return row[0]


def get_transaction_count() -> int:
    """Return the total number of rows in the transactions table."""
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()
    return row[0]


def get_all_monthly(period_start: datetime) -> list[sqlite3.Row]:
    """Return per-card, per-category spend totals from period_start to now."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT card_type, category, COALESCE(SUM(amount), 0) as total "
            "FROM transactions WHERE timestamp >= ? "
            "GROUP BY card_type, category",
            (period_start.isoformat(),),
        ).fetchall()
    return rows
