import sqlite3
import os
from contextlib import contextmanager
from smart_money.config import DB_PATH, DATA_DIR


SCHEMA = """
CREATE TABLE IF NOT EXISTS gurus (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    firm TEXT NOT NULL,
    cik TEXT UNIQUE,
    active INTEGER DEFAULT 1,
    notes TEXT,
    last_updated TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guru_id INTEGER NOT NULL REFERENCES gurus(id),
    report_period TEXT NOT NULL,
    filing_date TEXT NOT NULL,
    accession_number TEXT NOT NULL,
    cusip TEXT NOT NULL,
    issuer TEXT NOT NULL,
    ticker TEXT,
    class_title TEXT,
    value_usd INTEGER NOT NULL,
    shares INTEGER NOT NULL,
    share_type TEXT DEFAULT 'SH',
    put_call TEXT,
    portfolio_weight REAL,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(guru_id, report_period, cusip, put_call)
);

CREATE INDEX IF NOT EXISTS idx_holdings_ticker ON holdings(ticker);
CREATE INDEX IF NOT EXISTS idx_holdings_guru_period ON holdings(guru_id, report_period);
CREATE INDEX IF NOT EXISTS idx_holdings_accession ON holdings(accession_number);

CREATE TABLE IF NOT EXISTS cusip_ticker_map (
    cusip TEXT PRIMARY KEY,
    ticker TEXT,
    issuer_name TEXT,
    source TEXT DEFAULT 'edgartools',
    resolved_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS processed_filings (
    accession_number TEXT PRIMARY KEY,
    guru_id INTEGER NOT NULL,
    report_period TEXT NOT NULL,
    filing_date TEXT NOT NULL,
    total_value_usd INTEGER,
    num_holdings INTEGER,
    processed_at TEXT DEFAULT (datetime('now'))
);
"""


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    with get_db() as conn:
        conn.executescript(SCHEMA)
    print(f"Database initialized at {DB_PATH}")


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def store_holdings(conn, guru_id, filing_data):
    accession = filing_data["accession_number"]

    existing = conn.execute(
        "SELECT 1 FROM processed_filings WHERE accession_number = ?",
        (accession,)
    ).fetchone()
    if existing:
        return False

    total_value = float(filing_data["total_value"] or 0)

    for h in filing_data["holdings"]:
        value = int(float(h.get("value_usd", 0) or 0))
        shares = int(float(h.get("shares", 0) or 0))
        weight = float((value / total_value * 100) if total_value > 0 else 0)

        conn.execute("""
            INSERT OR REPLACE INTO holdings
            (guru_id, report_period, filing_date, accession_number,
             cusip, issuer, ticker, class_title, value_usd, shares,
             share_type, put_call, portfolio_weight)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            guru_id,
            filing_data["report_period"],
            filing_data["filing_date"],
            accession,
            h.get("cusip", ""),
            h.get("issuer", ""),
            h.get("ticker"),
            h.get("class_title"),
            value,
            shares,
            h.get("share_type", "SH"),
            h.get("put_call", ""),
            round(weight, 4),
        ))

    conn.execute("""
        INSERT OR REPLACE INTO processed_filings
        (accession_number, guru_id, report_period, filing_date,
         total_value_usd, num_holdings)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        accession,
        guru_id,
        filing_data["report_period"],
        filing_data["filing_date"],
        total_value,
        len(filing_data["holdings"]),
    ))

    return True
