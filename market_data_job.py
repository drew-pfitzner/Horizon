"""Background jobs for the Market Check: the S5FI rebuild and the daily auto-fill.

Two things run here, on the sm_job / alert_job pattern (worker thread + ring
buffer + single-flight lock):

  * refresh_s5fi() — recomputes the % of S&P 500 members above their 50DMA.
    Takes a minute or two (see market_data.compute_s5fi), so it never runs
    inline in a request; the UI starts it and polls for the result.
  * auto_fill() — fetches all six indicators and upserts the day's market_check
    row, so the gate is already computed when you open the app.

The scheduler wakes once a day at `mc_auto_time` (US/Eastern, after the close)
and, on boot, catches up if the box was off when that time passed.
"""
import threading
from collections import deque
from datetime import datetime, date, timedelta

from db import get_setting, set_setting
import market_data

ET = None  # bound lazily from alert_job so the ZoneInfo import stays in one place
_MAX_LOG_LINES = 200

_s5fi_lock = threading.Lock()
_fill_lock = threading.Lock()
_state_lock = threading.Lock()
_state = {
    "status": "idle",          # idle | running | done | error
    "started_at": None,
    "finished_at": None,
    "result": None,
    "output": deque(maxlen=_MAX_LOG_LINES),
    "error": None,
}
_timer_thread = None
_stop = threading.Event()


def _et():
    global ET
    if ET is None:
        from alert_job import ET as _ET
        ET = _ET
    return ET


# ─────────────────────────── state helpers ───────────────────────────

def get_state():
    with _state_lock:
        return {
            "status": _state["status"],
            "started_at": _state["started_at"],
            "finished_at": _state["finished_at"],
            "result": _state["result"],
            "output": list(_state["output"]),
            "error": _state["error"],
        }


def _append(line):
    with _state_lock:
        _state["output"].append(str(line))


def _set(**kw):
    with _state_lock:
        for k, v in kw.items():
            _state[k] = v


def is_running():
    return _s5fi_lock.locked()


# ─────────────────────────── S5FI refresh ───────────────────────────

def refresh_s5fi():
    """Recompute and cache S5FI. Returns the result dict, or a busy marker."""
    if not _s5fi_lock.acquire(blocking=False):
        return {"busy": True}
    _set(status="running", started_at=datetime.utcnow().isoformat() + "Z",
         finished_at=None, result=None, error=None)
    with _state_lock:
        _state["output"].clear()
    try:
        result = market_data.compute_s5fi(log=_append)
        market_data.store_s5fi(result)
        if result.get("error"):
            _set(status="error", error=result["error"], result=result)
        else:
            _set(status="done", result=result)
        return result
    except Exception as e:
        _append(f"ERROR: {e}")
        _set(status="error", error=str(e))
        return {"value": None, "error": str(e)}
    finally:
        _set(finished_at=datetime.utcnow().isoformat() + "Z")
        _s5fi_lock.release()


def start_s5fi_refresh():
    """Kick the recompute off in a thread. False if one is already running."""
    if is_running():
        return False
    threading.Thread(target=refresh_s5fi, daemon=True).start()
    return True


# ─────────────────────────── daily auto-fill ───────────────────────────

def auto_fill(force_s5fi=True, save=True, day=None):
    """Fetch all six indicators and (optionally) save the day's market check.

    Recomputes S5FI first when the cached reading is for an older bar, so the
    saved row isn't part-fresh. Returns {snapshot, saved, date, missing}.
    """
    if not _fill_lock.acquire(blocking=False):
        return {"busy": True}
    try:
        cache, stale = market_data.cached_s5fi()
        if force_s5fi and stale:
            _append("S5FI is stale — recomputing before the fill")
            refresh_s5fi()

        snap = market_data.snapshot()
        form = market_data.to_form(snap)
        missing = [k for k in ("st_louis_fed", "vix", "rsi", "stochastic",
                               "s5fi", "fear_greed") if k not in form]
        day = day or _session_date()
        saved = False
        if save and not missing:
            from routes.market_check import upsert_values
            upsert_values(day, form, notes_if_new="Auto-filled from live data")
            saved = True
            set_setting("mc_auto_last_run", datetime.now(_et()).isoformat(timespec="seconds"))
        elif missing:
            _append(f"not saved — no value for: {', '.join(missing)}")
        return {"snapshot": snap, "saved": saved, "date": day, "missing": missing}
    finally:
        _fill_lock.release()


def _session_date():
    """The date to file the check under: the US market date at run time.

    The scheduler fires after the 4pm ET close, so this is the session the
    numbers describe. A manual run earlier in the day files under the same US
    date carrying the previous close — exactly what reading the chart that
    morning would have given you. Callers with a user in front of them (the
    Market Check tab) pass the browser's own date instead.
    """
    return datetime.now(_et()).date().isoformat()


# ─────────────────────────── scheduler ───────────────────────────

def _next_run_delay(now_et):
    """Seconds until the next occurrence of mc_auto_time (ET)."""
    hhmm = get_setting("mc_auto_time", "16:40") or "16:40"
    try:
        hh, mm = (int(x) for x in hhmm.split(":"))
    except (ValueError, AttributeError):
        hh, mm = 16, 40
    target = now_et.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now_et:
        target += timedelta(days=1)
    return max(1.0, (target - now_et).total_seconds())


def _ran_today(now_et):
    last = get_setting("mc_auto_last_run", "") or ""
    return last[:10] == now_et.date().isoformat()


def _loop():
    # Boot catch-up: if today's run time has already passed and the box was off
    # for it, fill now rather than waiting until tomorrow.
    now_et = datetime.now(_et())
    if get_setting("mc_auto_enabled", False) and not _ran_today(now_et) \
            and _next_run_delay(now_et) > 12 * 3600:
        _append("Boot catch-up fill")
        try:
            auto_fill()
        except Exception as e:
            _append(f"catch-up failed: {e}")

    while not _stop.is_set():
        delay = _next_run_delay(datetime.now(_et()))
        # Wake hourly so a settings change lands without a full day's wait.
        if _stop.wait(min(delay, 3600)):
            break
        if delay <= 3600 and get_setting("mc_auto_enabled", False):
            try:
                auto_fill()
            except Exception as e:
                _append(f"scheduled fill failed: {e}")


def start_scheduler():
    """Start the daily timer thread (idempotent)."""
    global _timer_thread
    if _timer_thread and _timer_thread.is_alive():
        return
    _stop.clear()
    _timer_thread = threading.Thread(target=_loop, daemon=True)
    _timer_thread.start()
