import json
import sqlite3
from contextlib import contextmanager
from config import HORIZON_DB, SMART_MONEY_DB
from signals import DEFAULTS as SIGNAL_DEFAULTS


DEFAULT_SETTINGS = {
    "pullback_thresholds": {
        "rsi": {"low": 30, "mid": 60},
        "stochastic": {"low": 20, "mid": 80},
        "s5fi": {"low": 40, "mid": 70},
        "fear_greed": {"low": 45, "mid": 55},
    },
    "sec_identity": "",
    "portfolio": {"value": 0, "currency": "AUD"},
    "max_position_pct": 5.0,
    "fx_rates": {},
    # Alerts
    "ntfy_server": "https://ntfy.sh",
    "ntfy_topic": "",            # empty = alerts disabled until set (use a long random topic)
    "alert_enabled": False,
    "alert_check_time": "16:20",  # US/Eastern; shortly after the 4pm close
    # Signal thresholds — mirror the TradingView "Horizon Signal" inputs so alerts
    # match the chart.
    "alert_signal": dict(SIGNAL_DEFAULTS),
}


def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS market_check (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                st_louis_fed REAL,
                vix REAL,
                rsi REAL,
                stochastic REAL,
                s5fi REAL,
                fear_greed REAL,
                crash_risk TEXT,
                position_size_level TEXT,
                position_size_pct REAL,
                notes TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS valuations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                company_name TEXT,
                valuation_date TEXT,
                current_price REAL,
                roe1 REAL, roe2 REAL, roe3 REAL, roe4 REAL, roe5 REAL,
                payout1 REAL, payout2 REAL, payout3 REAL, payout4 REAL, payout5 REAL,
                required_return REAL DEFAULT 10.0,
                total_equity_m REAL,
                shares_outstanding_m REAL,
                net_profit_margin REAL,
                smart_money_holding REAL,
                equity_per_share REAL,
                roe_avg REAL, roe_median REAL, roe_mos REAL,
                payout_avg REAL, payout_median REAL, payout_mos REAL,
                distributed_avg REAL, distributed_median REAL, distributed_mos REAL,
                reinvested_avg REAL, reinvested_median REAL, reinvested_mos REAL,
                multiplier_avg REAL, multiplier_median REAL, multiplier_mos REAL,
                valuation_avg REAL, valuation_median REAL, valuation_mos REAL,
                discount_avg_pct REAL, discount_median_pct REAL, discount_mos_pct REAL,
                assessment TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS researched_stocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                company_name TEXT,
                date_researched TEXT,
                f_roa INTEGER DEFAULT 0,
                f_roe INTEGER DEFAULT 0,
                f_roi INTEGER DEFAULT 0,
                f_npm INTEGER DEFAULT 0,
                f_eps_5yr INTEGER DEFAULT 0,
                f_eps_1yr INTEGER DEFAULT 0,
                f_eps_next INTEGER DEFAULT 0,
                f_sales_5yr INTEGER DEFAULT 0,
                f_current_ratio INTEGER DEFAULT 0,
                f_debt_equity INTEGER DEFAULT 0,
                fundamentals_score INTEGER DEFAULT 0,
                market_cap_ok INTEGER DEFAULT 0,
                sm_holding_5pct INTEGER DEFAULT 0,
                sm_top3_increasing INTEGER DEFAULT 0,
                liquidity_ok INTEGER DEFAULT 0,
                tech_rsi_ok INTEGER DEFAULT 0,
                tech_sto_ok INTEGER DEFAULT 0,
                tech_cross_ok INTEGER DEFAULT 0,
                price_below_mos INTEGER DEFAULT 0,
                decision TEXT DEFAULT 'NO_ACTION',
                notes TEXT,
                latest_valuation_id INTEGER REFERENCES valuations(id),
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                company_name TEXT,
                sector TEXT,
                industry TEXT,
                strategy TEXT,
                currency TEXT DEFAULT 'USD',
                entry_date TEXT,
                entry_price REAL,
                shares REAL,
                position_size_pct REAL,
                exit_date TEXT,
                exit_price REAL,
                pl_dollar REAL,
                roi_pct REAL,
                days_held INTEGER,
                win_loss TEXT DEFAULT 'HOLD',
                notes TEXT,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS company_info_cache (
                ticker TEXT PRIMARY KEY,
                company_name TEXT,
                sector TEXT,
                industry TEXT,
                cik TEXT,
                source TEXT,
                fetched_at TEXT
            );

            CREATE TABLE IF NOT EXISTS alert_watch (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL UNIQUE,
                bucket TEXT NOT NULL DEFAULT 'BUY',   -- BUY | HELD
                kind TEXT NOT NULL DEFAULT 'Trade',   -- Trade | Invest
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS alert_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                bucket TEXT,          -- BUY | HELD (list it was in when it fired)
                action TEXT,          -- BUY | ADD | SELL (what the signal wants)
                signal_dir TEXT,      -- BUY | SELL (raw engine direction; dedupe axis)
                kind TEXT,
                bar_date TEXT,        -- daily bar the signal fired on (dedupe key)
                price REAL,
                message TEXT,
                sent_at TEXT,
                transport TEXT,
                ok INTEGER,           -- 1 = pushed OK, 0 = fetch/send failure
                error TEXT
            );
        """)
        for k, v in DEFAULT_SETTINGS.items():
            db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (k, json.dumps(v)),
            )


@contextmanager
def get_db():
    conn = sqlite3.connect(str(HORIZON_DB))
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


@contextmanager
def get_sm_db():
    conn = sqlite3.connect(f"file:{SMART_MONEY_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def get_setting(key, default=None):
    with get_db() as db:
        row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except (TypeError, ValueError):
        return default


def set_setting(key, value):
    with get_db() as db:
        db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )
