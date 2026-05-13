"""Background job runner for the smart_money ETL update.

Spawns `python cli.py update` in the SMART_MONEY_DIR as a subprocess and
streams stdout into an in-memory ring buffer. A single in-process job
runs at a time; status is exposed via get_state().
"""
import os
import sys
import subprocess
import threading
from datetime import datetime
from collections import deque

from config import SMART_MONEY_DIR

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


def _run():
    try:
        if not SMART_MONEY_DIR.exists():
            raise RuntimeError(f"SMART_MONEY_DIR not found: {SMART_MONEY_DIR}")

        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")

        venv_py = SMART_MONEY_DIR / "venv" / "bin" / "python"
        py = str(venv_py) if venv_py.exists() else sys.executable

        _append(f"$ {py} cli.py update  (cwd={SMART_MONEY_DIR})")
        proc = subprocess.Popen(
            [py, "cli.py", "update"],
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
        else:
            _set(status="error", error=f"exit code {proc.returncode}")
    except Exception as e:
        _append(f"ERROR: {e}")
        _set(status="error", error=str(e))
    finally:
        _set(finished_at=datetime.utcnow().isoformat() + "Z")
