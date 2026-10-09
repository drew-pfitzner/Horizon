"""Nightly app auto-update — the Settings "Update & Restart" button on a timer.

Once a day it fetches, and if upstream has moved, pulls (fast-forward only)
and restarts, exactly as the button does (routes.system.pull_and_restart).

  * On by default: the point is never having to open Settings to stay current.
  * Daily slot in US/Eastern like every other job. The default, 11:00 ET, is
    ~2–3am in Sydney and inside US market hours, when no other job runs.
  * Never restarts over work in flight: if an alert check, 13F update, S5FI
    rebuild or market-check fill is running, it waits for the next hourly wake.
  * Boot catch-up: a box that was off through the slot checks when it next
    comes up (after a short settle delay).
  * A dirty working tree or a non-fast-forward pull is reported, not forced.
"""
import threading
from datetime import datetime, timedelta

from db import get_setting, set_setting

DEFAULT_TIME = "11:00"
_BOOT_DELAY = 120  # let the app finish starting before a catch-up restart

_thread = None
_stop = threading.Event()


def _now():
    from alert_job import ET
    return datetime.now(ET)


def enabled():
    return bool(get_setting("auto_update_enabled", True))


def _slot_time():
    hhmm = get_setting("auto_update_time", DEFAULT_TIME) or DEFAULT_TIME
    try:
        hh, mm = (int(x) for x in hhmm.split(":"))
        return hh, mm
    except (ValueError, AttributeError):
        return 11, 0


def _next_slot(now):
    hh, mm = _slot_time()
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def _due(now):
    """True if the most recent slot has passed and we haven't checked since."""
    last = get_setting("auto_update_last_check", "") or ""
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
    except ValueError:
        return True
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=now.tzinfo)
    return last_dt < _next_slot(now) - timedelta(days=1)


def _busy():
    """Name of a job a restart would kill, or None."""
    import alert_job
    import sm_job
    import market_data_job
    if alert_job.is_running():
        return "alert check"
    if sm_job.is_running():
        return "smart money update"
    if market_data_job.is_running() or market_data_job._fill_lock.locked():
        return "market data fetch"
    return None


def run_once():
    """One scheduled attempt. Returns the recorded result string."""
    from routes.system import pull_and_restart, _git_available
    now = _now()
    busy = _busy()
    if busy:
        # Not stamped, so the next hourly wake tries again.
        return f"waiting — {busy} running"
    if not _git_available():
        result = "skipped — not a git checkout"
        ok, data = False, None
    else:
        # Stamp first: a successful update restarts the process before we'd
        # get another chance to write anything.
        set_setting("auto_update_last_check", now.isoformat(timespec="seconds"))
        ok, data = pull_and_restart()
        if not ok:
            result = f"failed — {data}"
        elif data.get("restarting"):
            result = f"updated {data['before']} → {data['after']}, restarting"
            if data.get("deps_error"):
                result += f" (dependency install failed: {data['deps_error']})"
        else:
            result = "already up to date"
    set_setting("auto_update_last_check", now.isoformat(timespec="seconds"))
    set_setting("auto_update_last_result", result)
    return result


def _loop():
    if _stop.wait(_BOOT_DELAY):
        return
    while not _stop.is_set():
        if enabled() and _due(_now()):
            run_once()
        delay = (_next_slot(_now()) - _now()).total_seconds()
        # Hourly wake: picks up a changed time, and retries a run that was
        # held back by a busy job.
        if _stop.wait(max(1.0, min(delay, 3600))):
            break


def start_scheduler():
    """Start the nightly timer thread (idempotent)."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True)
    _thread.start()


def schedule_info():
    now = _now()
    hh, mm = _slot_time()
    return {
        "enabled": enabled(),
        "time": f"{hh:02d}:{mm:02d}",
        "timezone": "US/Eastern",
        "next_run": _next_slot(now).isoformat(timespec="seconds"),
        "last_check": get_setting("auto_update_last_check", None),
        "last_result": get_setting("auto_update_last_result", None),
    }
