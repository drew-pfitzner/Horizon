"""Alert scheduler — evaluates watched tickers and pushes buy/sell signals.

Design goals (see ALERTS_PLAN.md):
  * Works end-of-day AND catches up on startup/resume (non-24/7 boxes).
  * ET-aware: the container clock is UTC, so the daily close and check time are
    computed in US/Eastern, and today's in-progress bar is dropped until close.
  * Bar-date dedupe: a signal fires at most once per (ticker, direction); stored
    bar dates prevent re-firing across restarts.
  * Single-flight: the timer and a manual "Check now" can't overlap.

Reuses the sm_job background-thread + ring-buffer pattern.
"""
import threading
from collections import deque
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from db import get_db, get_setting
from prices import fetch_history
from signals import evaluate
from notify import push_signal

ET = ZoneInfo("America/New_York")
MARKET_CLOSE_HOUR = 16  # 4pm ET; today's bar isn't final before this
_MAX_LOG_LINES = 200

_run_lock = threading.Lock()      # single-flight: one evaluation pass at a time
_state_lock = threading.Lock()
_state = {
    "status": "idle",             # idle | running | done | error
    "started_at": None,
    "finished_at": None,
    "last_summary": None,
    "output": deque(maxlen=_MAX_LOG_LINES),
    "error": None,
}
_timer_thread = None
_stop = threading.Event()


# ─────────────────────────── state helpers ───────────────────────────

def get_state():
    with _state_lock:
        return {
            "status": _state["status"],
            "started_at": _state["started_at"],
            "finished_at": _state["finished_at"],
            "last_summary": _state["last_summary"],
            "output": list(_state["output"]),
            "error": _state["error"],
        }


def _append(line):
    with _state_lock:
        _state["output"].append(line)


def _set(**kw):
    with _state_lock:
        for k, v in kw.items():
            _state[k] = v


def is_running():
    return _run_lock.locked()


# ─────────────────────────── evaluation core ───────────────────────────

def _completed_bars(bars, now_et):
    """Drop today's in-progress bar (before the ET close) so we never evaluate
    an unfinished daily candle. Weekends/holidays have no today-bar → no-op."""
    if bars and bars[-1]["date"] == now_et.strftime("%Y-%m-%d") \
            and now_et.hour < MARKET_CLOSE_HOUR:
        return bars[:-1]
    return bars


def _set_checked(db, ticker, bar_date):
    """Advance the per-ticker watermark to the latest evaluated bar."""
    db.execute(
        "UPDATE alert_watch SET last_checked_bar = ? WHERE ticker = ?",
        (bar_date, ticker),
    )


def _log(db, *, ticker, bucket, action, direction, kind, bar_date, price,
         message, ok, error):
    db.execute(
        "INSERT INTO alert_log (ticker, bucket, action, signal_dir, kind, "
        "bar_date, price, message, sent_at, transport, ok, error) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ticker, bucket, action, direction, kind, bar_date, price, message,
         datetime.utcnow().isoformat() + "Z", "ntfy", 1 if ok else 0, error),
    )


def run_checks():
    """Evaluate every active watch and push any due signals. Returns a summary
    dict. Safe to call concurrently — a second caller gets a 'busy' result."""
    if not _run_lock.acquire(blocking=False):
        return {"busy": True}
    _set(status="running", started_at=datetime.utcnow().isoformat() + "Z",
         finished_at=None, error=None)
    now_et = datetime.now(ET)
    signal_params = get_setting("alert_signal", None)
    fired, failed, checked = 0, 0, 0
    try:
        with get_db() as db:
            watches = db.execute(
                "SELECT ticker, bucket, kind, last_checked_bar FROM alert_watch "
                "WHERE active = 1 ORDER BY ticker"
            ).fetchall()

            for w in watches:
                ticker, bucket, kind = w["ticker"], w["bucket"], w["kind"]
                last_checked = w["last_checked_bar"]
                checked += 1
                bars, source = fetch_history(ticker)
                if not bars:
                    failed += 1
                    _append(f"{ticker}: price fetch failed")
                    _log(db, ticker=ticker, bucket=bucket, action=None,
                         direction=None, kind=kind, bar_date=None, price=None,
                         message=None, ok=False, error="price fetch failed")
                    continue

                bars = _completed_bars(bars, now_et)
                if not bars:
                    continue
                latest_bar = bars[-1]["date"]

                # First time this ticker is evaluated: arm it at the current bar
                # and fire NOTHING. Only bars that close *after* this point ever
                # alert — matching TradingView (no back-fill of stale history).
                if not last_checked:
                    _set_checked(db, ticker, latest_bar)
                    _append(f"{ticker}: armed at {latest_bar} (no back-fill)")
                    continue

                if latest_bar <= last_checked:
                    continue  # no new completed bar since last check

                series = evaluate(bars, kind=kind, params=signal_params)
                directions = ["BUY"] if bucket == "BUY" else ["BUY", "SELL"]
                # Only bars newer than the watermark are eligible (catch-up window).
                eligible = [s for s in series if s["date"] > last_checked]

                send_failed = False
                for direction in directions:
                    key = "buy" if direction == "BUY" else "sell"
                    hits = [s for s in eligible if s[key]]
                    if not hits:
                        continue
                    sig = hits[-1]  # only the latest edge in the window
                    ok, err, title, body = push_signal(
                        bucket, kind, direction, ticker, sig["close"],
                        rsi=sig["rsi"], d=sig["d"])
                    action = "ADD" if (bucket == "HELD" and direction == "BUY") else direction
                    _log(db, ticker=ticker, bucket=bucket, action=action,
                         direction=direction, kind=kind, bar_date=sig["date"],
                         price=sig["close"], message=f"{title} — {body}",
                         ok=ok, error=err)
                    if ok:
                        fired += 1
                        _append(f"{ticker}: {action} @ {sig['date']} — sent")
                    else:
                        failed += 1
                        send_failed = True
                        _append(f"{ticker}: {action} @ {sig['date']} — send failed: {err}")

                # Advance the watermark only if delivery succeeded; a failed push
                # (ntfy down / topic not set) is retried on the next run, and since
                # we only ever fire the latest hit in the window it won't pile up.
                if not send_failed:
                    _set_checked(db, ticker, latest_bar)

        summary = {"checked": checked, "fired": fired, "failed": failed,
                   "at": now_et.isoformat()}
        _set(status="done", last_summary=summary)
        return summary
    except Exception as e:
        _append(f"ERROR: {e}")
        _set(status="error", error=str(e))
        return {"error": str(e), "checked": checked, "fired": fired}
    finally:
        _set(finished_at=datetime.utcnow().isoformat() + "Z")
        _run_lock.release()


# ─────────────────────────── scheduler thread ───────────────────────────

def _next_check_delay(now_et):
    """Seconds until the next occurrence of alert_check_time (ET)."""
    hhmm = get_setting("alert_check_time", "16:20") or "16:20"
    try:
        hh, mm = (int(x) for x in hhmm.split(":"))
    except (ValueError, AttributeError):
        hh, mm = 16, 20
    target = now_et.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now_et:
        target += timedelta(days=1)
    return max(1.0, (target - now_et).total_seconds())


def _loop():
    # On boot: catch up immediately on anything missed while the box was off.
    if get_setting("alert_enabled", False):
        _append("Boot catch-up run")
        run_checks()
    while not _stop.is_set():
        delay = _next_check_delay(datetime.now(ET))
        # Wake at least hourly so a mid-day settings change (check time / enable)
        # is picked up without waiting a full day.
        if _stop.wait(min(delay, 3600)):
            break
        if delay <= 3600 and get_setting("alert_enabled", False):
            run_checks()


def start_scheduler():
    """Start the background timer thread (idempotent)."""
    global _timer_thread
    if _timer_thread and _timer_thread.is_alive():
        return
    _stop.clear()
    _timer_thread = threading.Thread(target=_loop, daemon=True)
    _timer_thread.start()
