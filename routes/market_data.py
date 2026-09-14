"""Live indicator feed for the Market Check — see market_data.py for sources."""
from flask import Blueprint, request, jsonify

import market_data
import market_data_job
from db import get_setting, set_setting

bp = Blueprint("market_data", __name__)


@bp.route("/snapshot", methods=["GET"])
def snapshot():
    """All six indicators. Fast — S5FI comes from cache with a `stale` flag;
    start /s5fi/refresh if you need it recomputed."""
    return jsonify({"success": True, "data": market_data.snapshot()})


@bp.route("/s5fi/refresh", methods=["POST"])
def refresh_s5fi():
    if not market_data_job.start_s5fi_refresh():
        return jsonify({"success": False, "error": "already computing"}), 409
    return jsonify({"success": True, "data": market_data_job.get_state()})


@bp.route("/s5fi/status", methods=["GET"])
def s5fi_status():
    return jsonify({"success": True, "data": market_data_job.get_state()})


@bp.route("/auto-fill", methods=["POST"])
def auto_fill():
    """Run the scheduled fill on demand. `save=false` previews without writing."""
    p = request.get_json(silent=True) or {}
    result = market_data_job.auto_fill(
        force_s5fi=p.get("force_s5fi", True),
        save=p.get("save", True),
        day=(p.get("date") or "").strip() or None,
    )
    if result.get("busy"):
        return jsonify({"success": False, "error": "a fill is already running"}), 409
    return jsonify({"success": True, "data": result})


@bp.route("/auto", methods=["GET"])
def get_auto():
    return jsonify({"success": True, "data": {
        "enabled": bool(get_setting("mc_auto_enabled", False)),
        "time": get_setting("mc_auto_time", "16:40"),
        "timezone": "US/Eastern",
        "last_run": get_setting("mc_auto_last_run", None),
    }})


@bp.route("/auto", methods=["PUT"])
def put_auto():
    p = request.get_json(force=True)
    if "enabled" in p:
        set_setting("mc_auto_enabled", bool(p["enabled"]))
    if "time" in p:
        t = (p.get("time") or "").strip()
        if not _valid_hhmm(t):
            return jsonify({"success": False, "error": "time must be HH:MM"}), 400
        set_setting("mc_auto_time", t)
    return get_auto()


def _valid_hhmm(t):
    try:
        hh, mm = (int(x) for x in t.split(":"))
    except (ValueError, AttributeError):
        return False
    return 0 <= hh <= 23 and 0 <= mm <= 59
