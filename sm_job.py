"""Background job runner for the smart_money ETL update.

Spawns `python cli.py update` in the SMART_MONEY_DIR as a subprocess and
streams stdout into an in-memory ring buffer. A single in-process job
runs at a time; status is exposed via get_state().
"""
import os
import sys
import sqlite3
import subprocess
import threading
from datetime import datetime, timedelta
from collections import deque

from config import SMART_MONEY_DIR, SMART_MONEY_DB
from db import get_setting

_MAX_LOG_LINES = 200

_state_lock = threading.Lock()
_state = {
    "status": "idle",  # idle | running | done | error
    "started_at": None,
    "finished_at": None,
    "output": deque(maxlen=_MAX_LOG_LINES),
    "error": None,
}
_thread = None


def get_state():
    with _state_lock:
        return {
            "status": _state["status"],
            "started_at": _state["started_at"],
            "finished_at": _state["finished_at"],
            "output": list(_state["output"]),
            "error": _state["error"],
        }


def _append(line):
    with _state_lock:
        _state["output"].append(line)


def _set(**kwargs):
    with _state_lock:
        for k, v in kwargs.items():
            _state[k] = v


def is_running():
    with _state_lock:
        return _state["status"] == "running"


def start():
    """Returns True if the job started, False if one was already running."""
    global _thread
    with _state_lock:
        if _state["status"] == "running":
            return False
        _state["status"] = "running"
        _state["started_at"] = datetime.utcnow().isoformat() + "Z"
        _state["finished_at"] = None
        _state["output"].clear()
        _state["error"] = None
    _thread = threading.Thread(target=_run, daemon=True)
    _thread.start()
    return True


def _db_needs_init():
    """True if the smart_money DB has no `gurus` table or is empty."""
    if not SMART_MONEY_DB.exists():
        return True
    try:
        conn = sqlite3.connect(str(SMART_MONEY_DB))
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='gurus'"
            ).fetchone()
            if not row:
                return True
            count = conn.execute("SELECT COUNT(*) FROM gurus").fetchone()[0]
            return count == 0
        finally:
            conn.close()
    except sqlite3.Error:
        return True


def _run():
    try:
        if not SMART_MONEY_DIR.exists():
            raise RuntimeError(f"SMART_MONEY_DIR not found: {SMART_MONEY_DIR}")

        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")

        sec_identity = get_setting("sec_identity", "")
        if sec_identity:
            env["SEC_IDENTITY"] = sec_identity

        venv_py = SMART_MONEY_DIR / "venv" / "bin" / "python"
        py = str(venv_py) if venv_py.exists() else sys.executable

        if _db_needs_init():
            sub_cmd = "init"
            _append("Smart money DB is empty — running first-time init (creates schema, seeds gurus, fetches 4 quarters). This takes 10–20 minutes.")
        else:
            sub_cmd = "update"

        _append(f"$ {py} cli.py {sub_cmd}  (cwd={SMART_MONEY_DIR})")
        proc = subprocess.Popen(
            [py, "cli.py", sub_cmd],
            cwd=str(SMART_MONEY_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            _append(line.rstrip())
        proc.wait()

        if proc.returncode == 0:
            _set(status="done")
            # Freshness stamp for the Home view. Written on success only, and by
            # *both* paths (button and scheduler) — `sm_last_auto_run` is the
            # scheduler's own slot bookkeeping and doesn't move when you press
            # Update, so it can't answer "how old is this data?".
            from db import set_setting as _set_setting
            _set_setting("sm_last_run", _local_now().isoformat(timespec="seconds"))
        else:
            _set(status="error", error=f"exit code {proc.returncode}")
    except Exception as e:
        _append(f"ERROR: {e}")
        _set(status="error", error=str(e))
    finally:
        _set(finished_at=datetime.utcnow().isoformat() + "Z")


# ─────────────────────────── weekly scheduler ───────────────────────────
#
# 13F filings land in bursts around the 45-day deadline after each quarter end,
# so a weekly poll is the right cadence: often a no-op, and never more than a
# week behind when a guru files. The job is the same `cli.py update` the button
# runs, so nothing diverges between the manual and automatic paths.

_sched_thread = None
_sched_stop = threading.Event()
_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday",
             "Friday", "Saturday", "Sunday"]


def _local_now():
    from alert_job import ET
    return datetime.now(ET)


def _next_run_delay(now):
    """Seconds until the next configured weekly slot (ET)."""
    from db import get_setting as _get
    try:
        day = int(_get("sm_update_day", 6))          # 0=Mon … 6=Sun
    except (TypeError, ValueError):
        day = 6
    day = day % 7
    hhmm = _get("sm_update_time", "07:00") or "07:00"
    try:
        hh, mm = (int(x) for x in hhmm.split(":"))
    except (ValueError, AttributeError):
        hh, mm = 7, 0
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    target += timedelta(days=(day - now.weekday()) % 7)
    if target <= now:
        target += timedelta(days=7)
    return max(1.0, (target - now).total_seconds())


def _due(now):
    """True if this week's slot has passed and we haven't run since it."""
    from db import get_setting as _get
    last = _get("sm_last_auto_run", "") or ""
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
    except ValueError:
        return True
    # The slot we most recently passed is one week before the next one.
    prev_slot = now + timedelta(seconds=_next_run_delay(now)) - timedelta(days=7)
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=now.tzinfo)
    return last_dt < prev_slot


def _run_scheduled():
    from db import set_setting as _set
    now = _local_now()
    if not start():
        return False   # a manual update is already running; next week will catch it
    _set("sm_last_auto_run", now.isoformat(timespec="seconds"))
    return True


def _sched_loop():
    from db import get_setting as _get
    # Boot catch-up: a laptop that was closed through Sunday morning still gets
    # its update when it next comes up, rather than skipping the week.
    if _get("sm_auto_enabled", False) and _due(_local_now()):
        _append("Weekly auto-update: catching up a missed run")
        _run_scheduled()

    while not _sched_stop.is_set():
        delay = _next_run_delay(_local_now())
        # Hourly wake so a changed day/time takes effect without a week's wait.
        if _sched_stop.wait(min(delay, 3600)):
            break
        from db import get_setting as _g
        if delay <= 3600 and _g("sm_auto_enabled", False):
            _run_scheduled()


def start_scheduler():
    """Start the weekly timer thread (idempotent)."""
    global _sched_thread
    if _sched_thread and _sched_thread.is_alive():
        return
    _sched_stop.clear()
    _sched_thread = threading.Thread(target=_sched_loop, daemon=True)
    _sched_thread.start()


def schedule_info():
    """What the UI shows: on/off, the slot, and when it next/last ran."""
    from db import get_setting as _get
    now = _local_now()
    delay = _next_run_delay(now)
    try:
        day = int(_get("sm_update_day", 6)) % 7
    except (TypeError, ValueError):
        day = 6
    return {
        "enabled": bool(_get("sm_auto_enabled", False)),
        "day": day,
        "day_name": _WEEKDAYS[day],
        "time": _get("sm_update_time", "07:00"),
        "timezone": "US/Eastern",
        "next_run": (now + timedelta(seconds=delay)).isoformat(timespec="seconds"),
        "last_auto_run": _get("sm_last_auto_run", None),
        # Last run that actually completed, whoever started it.
        "last_run": _get("sm_last_run", None) or _get("sm_last_auto_run", None),
    }
