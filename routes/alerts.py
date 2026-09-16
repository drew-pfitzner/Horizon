"""Alerts API — Buy / Held watch lists, settings, log, and runs.

Buckets (both derived automatically — see watch_sync.py):
  BUY  — fresh TRADE/INVEST research; watched for BUY signals only.
  HELD — open trades; watched for BUY (add) and SELL (exit) signals.
Directions watched are derived from the bucket; there is no free-form direction.
"""
import threading

from flask import Blueprint, request, jsonify

from db import get_db, get_setting, set_setting
from signals import DEFAULTS as SIGNAL_DEFAULTS, PARAM_BOUNDS
import alert_job
import watch_sync
import notify

bp = Blueprint("alerts", __name__)

_ALERT_SETTINGS = ("ntfy_server", "ntfy_topic", "alert_enabled", "alert_check_time",
                   "alert_research_max_months")


def _clean_signal(raw):
    """Coerce + clamp incoming signal params to valid values, filling from
    DEFAULTS. Unknown keys are dropped; out-of-range values are clamped."""
    out = dict(SIGNAL_DEFAULTS)
    if not isinstance(raw, dict):
        return out
    for key, default in SIGNAL_DEFAULTS.items():
        if key not in raw or raw[key] is None:
            continue
        val = raw[key]
        if isinstance(default, bool):
            out[key] = bool(val)
        else:
            try:
                val = int(val)
            except (TypeError, ValueError):
                continue
            lo, hi = PARAM_BOUNDS.get(key, (None, None))
            if lo is not None:
                val = max(lo, min(hi, val))
            out[key] = val
    return out


# ─────────────────────────── watch lists ───────────────────────────
# The lists are derived, not edited: open trades → Held, fresh TRADE/INVEST
# research → Buy. See watch_sync.py.

@bp.route("/watches", methods=["GET"])
def list_watches():
    info = watch_sync.sync()
    with get_db() as db:
        rows = db.execute(
            "SELECT id, ticker, bucket, kind, active, created_at, last_checked_bar "
            "FROM alert_watch WHERE active = 1 ORDER BY ticker"
        ).fetchall()
    watches = [dict(r) for r in rows]
    for w in watches:
        w["date_researched"] = info["research_dates"].get(w["ticker"])
    return jsonify({"success": True, "data": {
        "buy": [w for w in watches if w["bucket"] == "BUY"],
        "held": [w for w in watches if w["bucket"] == "HELD"],
        "stale": info["stale"],
        "max_months": info["max_months"],
    }})


# ─────────────────────────── settings ───────────────────────────

@bp.route("/settings", methods=["GET"])
def get_settings():
    return jsonify({"success": True, "data": {
        "ntfy_server": get_setting("ntfy_server", "https://ntfy.sh"),
        "ntfy_topic": get_setting("ntfy_topic", ""),
        "alert_enabled": get_setting("alert_enabled", False),
        "alert_check_time": get_setting("alert_check_time", "16:20"),
        "alert_research_max_months": watch_sync.max_research_months(),
        "signal": _clean_signal(get_setting("alert_signal", None)),
        "signal_defaults": dict(SIGNAL_DEFAULTS),
    }})


@bp.route("/settings", methods=["PUT"])
def put_settings():
    body = request.get_json(silent=True) or {}
    for key in _ALERT_SETTINGS:
        if key in body:
            val = body[key]
            if key == "alert_enabled":
                val = bool(val)
            elif key == "ntfy_topic":
                val = (val or "").strip()
            elif key == "alert_research_max_months":
                try:
                    val = max(0, min(120, int(val)))
                except (TypeError, ValueError):
                    continue
            set_setting(key, val)
    if "signal" in body:
        set_setting("alert_signal", _clean_signal(body["signal"]))
    return jsonify({"success": True})


# ─────────────────────────── log + runs ───────────────────────────

@bp.route("/log", methods=["GET"])
def get_log():
    limit = int(request.args.get("limit", 50))
    with get_db() as db:
        rows = db.execute(
            "SELECT id, ticker, bucket, action, signal_dir, kind, bar_date, price, "
            "message, sent_at, ok, error FROM alert_log "
            "ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return jsonify({"success": True, "data": [dict(r) for r in rows]})


@bp.route("/log/<int:log_id>", methods=["DELETE"])
def delete_log_entry(log_id):
    with get_db() as db:
        db.execute("DELETE FROM alert_log WHERE id = ?", (log_id,))
    return jsonify({"success": True})


@bp.route("/log", methods=["DELETE"])
def clear_log():
    """Clear the alert history. Safe: dedupe uses each watch's last_checked_bar
    watermark, not this log, so clearing never causes signals to re-fire."""
    with get_db() as db:
        db.execute("DELETE FROM alert_log")
    return jsonify({"success": True})


@bp.route("/check-now", methods=["POST"])
def check_now():
    if alert_job.is_running():
        return jsonify({"success": False, "error": "a check is already running"}), 409
    threading.Thread(target=alert_job.run_checks, daemon=True).start()
    return jsonify({"success": True})


@bp.route("/now", methods=["GET"])
def signal_now():
    """Current signal state for every active watch, ignoring dedupe. Read-only:
    sends nothing and moves no watermark. Network-bound, so the UI calls it on
    an explicit button press, not on mount."""
    return jsonify({"success": True, "data": alert_job.current_state()})


@bp.route("/status", methods=["GET"])
def status():
    return jsonify({"success": True, "data": alert_job.get_state()})


@bp.route("/test", methods=["POST"])
def test_push():
    ok, err = notify.send_test()
    if not ok:
        return jsonify({"success": False, "error": err}), 400
    return jsonify({"success": True})
