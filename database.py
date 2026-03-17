"""SQLite persistence layer for cc-spend transactions."""

import sqlite3
import threading
from datetime import datetime
import config

_write_lock = threading.Lock()

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
CREATE TABLE IF NOT EXISTS merchant_categories (
    merchant    TEXT PRIMARY KEY,
    category    TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'claude',
    updated_at  TEXT NOT NULL
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
    with _write_lock, _connect() as conn:
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


def get_merchant_category(merchant: str) -> str | None:
    """Return the cached category for a merchant (case-insensitive), or None."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT category FROM merchant_categories WHERE UPPER(merchant) = UPPER(?)",
            (merchant,),
        ).fetchone()
    return row["category"] if row else None


def upsert_merchant_category(merchant: str, category: str, source: str) -> None:
    """Insert or replace the category for a merchant."""
    now = datetime.utcnow().isoformat() + "Z"
    with _write_lock, _connect() as conn:
        conn.execute(
            "INSERT INTO merchant_categories (merchant, category, source, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(merchant) DO UPDATE SET category=excluded.category, "
            "source=excluded.source, updated_at=excluded.updated_at",
            (merchant.upper(), category, source, now),
        )


def update_transactions_category(merchant: str, category: str) -> int:
    """Retroactively update the category for all existing transactions matching merchant."""
    with _write_lock, _connect() as conn:
        cur = conn.execute(
            "UPDATE transactions SET category = ? WHERE UPPER(merchant) = UPPER(?)",
            (category, merchant),
        )
    return cur.rowcount


def get_all_merchant_categories() -> list[sqlite3.Row]:
    """Return all rows from merchant_categories ordered by merchant name."""
    with _connect() as conn:
        return conn.execute(
            "SELECT merchant, category, source, updated_at "
            "FROM merchant_categories ORDER BY merchant"
        ).fetchall()


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
