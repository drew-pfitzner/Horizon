"""Derive the alert watch lists from Research and Trades — nothing is added or
removed by hand.

  HELD — every ticker with an open trade (no exit_date). Kind follows the
         trade's strategy (INVEST → Invest, else Trade).
  BUY  — every ticker whose *latest* research decision is TRADE or INVEST,
         researched within `alert_research_max_months` (0 = no limit), and not
         already held. Kind follows the decision.

Anything else that is active gets soft-deleted (active = 0) so its
last_checked_bar watermark survives a quick drop-and-return (see the note on
soft delete in CLAUDE.md). A row that comes back after more than
REVIVE_GRACE_DAYS has its watermark cleared instead, so it re-arms at the
current bar rather than pushing a months-old signal from the catch-up window.

Called at the top of every read of the lists and every check, so a new trade,
a closed trade or a changed decision is reflected without any other hook.
"""
from datetime import date, datetime, timedelta

from db import get_db, get_setting

DEFAULT_MAX_MONTHS = 6
REVIVE_GRACE_DAYS = 7


def max_research_months():
    try:
        return max(0, int(get_setting("alert_research_max_months", DEFAULT_MAX_MONTHS)))
    except (TypeError, ValueError):
        return DEFAULT_MAX_MONTHS


def _months_ago(today, months):
    y, m = divmod(today.year * 12 + (today.month - 1) - months, 12)
    m += 1
    # Clamp the day for short months (e.g. 31 Aug − 6 months → 28/29 Feb).
    for day in (today.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue


def _kind(value):
    return "Invest" if (value or "").upper() == "INVEST" else "Trade"


def sync():
    """Bring alert_watch in line with trades + research. Returns what it decided,
    including the research tickers skipped for being too old."""
    months = max_research_months()
    cutoff = _months_ago(date.today(), months).isoformat() if months else None
    now = datetime.utcnow().isoformat() + "Z"

    with get_db() as db:
        # Open positions → HELD. Latest entry wins the kind if several are open.
        held = {}
        for r in db.execute(
            "SELECT ticker, strategy FROM trades WHERE exit_date IS NULL "
            "AND ticker IS NOT NULL ORDER BY entry_date, id"
        ).fetchall():
            t = r["ticker"].strip().upper()
            if t:
                held[t] = _kind(r["strategy"])

        # Latest research row per ticker → BUY if TRADE/INVEST and fresh enough.
        latest = {}
        for r in db.execute(
            "SELECT ticker, decision, COALESCE(date_researched, substr(updated_at, 1, 10)) AS d "
            "FROM researched_stocks WHERE ticker IS NOT NULL "
            "ORDER BY d, updated_at, id"
        ).fetchall():
            t = r["ticker"].strip().upper()
            if t:
                latest[t] = (r["decision"], r["d"])

        buy, stale = {}, []
        for t, (decision, d) in sorted(latest.items()):
            if (decision or "").upper() not in ("TRADE", "INVEST") or t in held:
                continue
            if cutoff and (not d or d < cutoff):
                stale.append({"ticker": t, "kind": _kind(decision), "date_researched": d})
                continue
            buy[t] = _kind(decision)

        wanted = {t: ("HELD", k) for t, k in held.items()}
        wanted.update({t: ("BUY", k) for t, k in buy.items()})

        existing = {r["ticker"]: dict(r) for r in db.execute(
            "SELECT id, ticker, bucket, kind, active, last_checked_bar FROM alert_watch"
        ).fetchall()}
        revive_floor = (date.today() - timedelta(days=REVIVE_GRACE_DAYS)).isoformat()

        for t, (bucket, kind) in wanted.items():
            row = existing.get(t)
            if row is None:
                db.execute(
                    "INSERT INTO alert_watch (ticker, bucket, kind, active, created_at) "
                    "VALUES (?, ?, ?, 1, ?)", (t, bucket, kind, now))
                continue
            watermark = row["last_checked_bar"]
            if not row["active"] and watermark and watermark < revive_floor:
                watermark = None
            if (row["bucket"], row["kind"], row["active"], row["last_checked_bar"]) != \
                    (bucket, kind, 1, watermark):
                db.execute(
                    "UPDATE alert_watch SET bucket = ?, kind = ?, active = 1, "
                    "last_checked_bar = ? WHERE id = ?",
                    (bucket, kind, watermark, row["id"]))

        for t, row in existing.items():
            if row["active"] and t not in wanted:
                db.execute("UPDATE alert_watch SET active = 0 WHERE id = ?", (row["id"],))

    return {"max_months": months, "cutoff": cutoff, "stale": stale,
            "research_dates": {t: latest[t][1] for t in buy}}
