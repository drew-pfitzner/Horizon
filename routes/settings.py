from flask import Blueprint, request, jsonify
from db import get_setting, set_setting, DEFAULT_SETTINGS


bp = Blueprint("settings", __name__)


@bp.route("/pullback-thresholds", methods=["GET"])
def get_pullback():
    data = get_setting("pullback_thresholds", DEFAULT_SETTINGS["pullback_thresholds"])
    return jsonify({"success": True, "data": data})


@bp.route("/pullback-thresholds", methods=["PUT"])
def put_pullback():
    p = request.get_json(force=True)
    required = {"rsi", "stochastic", "s5fi", "fear_greed"}
    if not required.issubset(p.keys()):
        return jsonify({"success": False, "error": "missing indicator keys"}), 400
    for k in required:
        v = p[k]
        if not isinstance(v, dict) or "low" not in v or "mid" not in v:
            return jsonify({"success": False, "error": f"{k} needs low + mid"}), 400
        try:
            v["low"] = float(v["low"])
            v["mid"] = float(v["mid"])
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": f"{k} thresholds must be numeric"}), 400
        if v["low"] >= v["mid"]:
            return jsonify({"success": False, "error": f"{k} low must be < mid"}), 400
    set_setting("pullback_thresholds", {k: p[k] for k in required})
    return jsonify({"success": True, "data": p})


@bp.route("/pullback-thresholds/reset", methods=["POST"])
def reset_pullback():
    defaults = DEFAULT_SETTINGS["pullback_thresholds"]
    set_setting("pullback_thresholds", defaults)
    return jsonify({"success": True, "data": defaults})
