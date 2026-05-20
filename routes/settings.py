from datetime import datetime, date
import requests
from flask import Blueprint, request, jsonify
from db import get_setting, set_setting, DEFAULT_SETTINGS


bp = Blueprint("settings", __name__)


def get_fx_rate(from_cur, to_cur, force_refresh=False):
    from_cur = (from_cur or "USD").upper()
    to_cur = (to_cur or "USD").upper()
    if from_cur == to_cur:
        return 1.0
    key = f"{from_cur}_{to_cur}"
    cache = get_setting("fx_rates", {}) or {}
    cached = cache.get(key)
    today = date.today().isoformat()
    fresh_today = cached and (cached.get("updated_at") or "")[:10] == today
    manual = cached and cached.get("source") == "manual"
    if not force_refresh and (fresh_today or manual):
        try:
            return float(cached["rate"])
        except (TypeError, ValueError, KeyError):
            pass
    try:
        r = requests.get(f"https://open.er-api.com/v6/latest/{from_cur}", timeout=8)
        data = r.json()
        if data.get("result") == "success":
            rate = data.get("rates", {}).get(to_cur)
            if rate:
                cache[key] = {
                    "rate": float(rate),
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "source": "open.er-api.com",
                }
                set_setting("fx_rates", cache)
                return float(rate)
    except Exception:
        pass
    if cached:
        try:
            return float(cached["rate"])
        except (TypeError, ValueError, KeyError):
            return None
    return None


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


@bp.route("/sec-identity", methods=["GET"])
def get_sec_identity():
    email = get_setting("sec_identity", DEFAULT_SETTINGS["sec_identity"])
    return jsonify({"success": True, "data": email})


@bp.route("/sec-identity", methods=["PUT"])
def put_sec_identity():
    p = request.get_json(force=True)
    email = p.get("email", "").strip()
    set_setting("sec_identity", email)
    return jsonify({"success": True, "data": email})


@bp.route("/portfolio", methods=["GET"])
def get_portfolio():
    data = get_setting("portfolio", DEFAULT_SETTINGS["portfolio"])
    return jsonify({"success": True, "data": data})


@bp.route("/portfolio", methods=["PUT"])
def put_portfolio():
    from routes.trades import recompute_open_positions
    p = request.get_json(force=True)
    try:
        value = float(p.get("value") or 0)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "value must be numeric"}), 400
    currency = (p.get("currency") or "AUD").upper().strip()
    if not currency:
        return jsonify({"success": False, "error": "currency required"}), 400
    set_setting("portfolio", {"value": value, "currency": currency})
    updated = recompute_open_positions()
    return jsonify({"success": True, "data": {"value": value, "currency": currency, "recomputed": updated}})


@bp.route("/max-position-pct", methods=["GET"])
def get_max_position():
    data = get_setting("max_position_pct", DEFAULT_SETTINGS["max_position_pct"])
    return jsonify({"success": True, "data": data})


@bp.route("/max-position-pct", methods=["PUT"])
def put_max_position():
    p = request.get_json(force=True)
    try:
        v = float(p.get("value"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "value must be numeric"}), 400
    if v <= 0 or v > 100:
        return jsonify({"success": False, "error": "value must be between 0 and 100"}), 400
    set_setting("max_position_pct", v)
    return jsonify({"success": True, "data": v})


@bp.route("/fx-rates", methods=["GET"])
def get_fx_rates():
    rates = get_setting("fx_rates", {}) or {}
    return jsonify({"success": True, "data": rates})


@bp.route("/fx-rates/refresh", methods=["POST"])
def refresh_fx_rate():
    p = request.get_json(force=True) or {}
    from_cur = (p.get("from") or "USD").upper()
    to_cur = (p.get("to") or "AUD").upper()
    rate = get_fx_rate(from_cur, to_cur, force_refresh=True)
    if rate is None:
        return jsonify({"success": False, "error": "could not fetch rate"}), 502
    cache = get_setting("fx_rates", {}) or {}
    return jsonify({"success": True, "data": {"rate": rate, "entry": cache.get(f"{from_cur}_{to_cur}")}})


@bp.route("/fx-rates", methods=["PUT"])
def put_fx_rate():
    p = request.get_json(force=True)
    from_cur = (p.get("from") or "").upper().strip()
    to_cur = (p.get("to") or "").upper().strip()
    try:
        rate = float(p.get("rate"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "rate must be numeric"}), 400
    if not from_cur or not to_cur or rate <= 0:
        return jsonify({"success": False, "error": "from, to, and positive rate required"}), 400
    cache = get_setting("fx_rates", {}) or {}
    cache[f"{from_cur}_{to_cur}"] = {
        "rate": rate,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "manual",
    }
    set_setting("fx_rates", cache)
    return jsonify({"success": True, "data": cache[f"{from_cur}_{to_cur}"]})
