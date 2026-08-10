"""Alerts API — manage the Buy / Held watch lists, settings, log, and runs.

Buckets:
  BUY  — tickers you want to open; watched for BUY signals only.
  HELD — tickers you own; watched for BUY (add) and SELL (exit) signals.
Directions watched are derived from the bucket; there is no free-form direction.
"""
import threading
from datetime import datetime

from flask import Blueprint, request, jsonify

from db import get_db, get_setting, set_setting
from signals import DEFAULTS as SIGNAL_DEFAULTS, PARAM_BOUNDS
import alert_job
import notify

bp = Blueprint("alerts", __name__)

_ALERT_SETTINGS = ("ntfy_server", "ntfy_topic", "alert_enabled", "alert_check_time")


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


def _kind_from_decision(decision):
    d = (decision or "").upper()
    if d == "INVEST":
        return "Invest"
    return "Trade"  # TRADE and everything else default to Trade thresholds


# ─────────────────────────── watch lists ───────────────────────────

@bp.route("/watches", methods=["GET"])
def list_watches():
    with get_db() as db:
        rows = db.execute(
            "SELECT id, ticker, bucket, kind, active, created_at, last_checked_bar "
            "FROM alert_watch WHERE active = 1 ORDER BY ticker"
        ).fetchall()
    watches = [dict(r) for r in rows]
    return jsonify({"success": True, "data": {
        "buy": [w for w in watches if w["bucket"] == "BUY"],
        "held": [w for w in watches if w["bucket"] == "HELD"],
    }})


@bp.route("/watches", methods=["POST"])
def add_watch():
    body = request.get_json(silent=True) or {}
    ticker = (body.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify({"success": False, "error": "ticker required"}), 400
    bucket = "HELD" if (body.get("bucket") or "BUY").upper() == "HELD" else "BUY"
    kind = "Invest" if (body.get("kind") or "Trade") == "Invest" else "Trade"
    with get_db() as db:
        db.execute(
            "INSERT INTO alert_watch (ticker, bucket, kind, active, created_at) "
            "VALUES (?, ?, ?, 1, ?) "
            "ON CONFLICT(ticker) DO UPDATE SET "
            "  bucket = excluded.bucket, kind = excluded.kind, active = 1",
            (ticker, bucket, kind, datetime.utcnow().isoformat() + "Z"),
        )
    return jsonify({"success": True})


@bp.route("/from-research", methods=["POST"])
def add_from_research():
    """One-click 'Watch to Buy' from the Research view. Seeds the BUY list and
    carries kind from the research decision. Does not downgrade a HELD ticker."""
    body = request.get_json(silent=True) or {}
    ticker = (body.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify({"success": False, "error": "ticker required"}), 400
    kind = _kind_from_decision(body.get("decision"))
    with get_db() as db:
        # Keep an existing bucket (e.g. HELD) untouched; only ensure it's active
        # and BUY-seed when new.
        db.execute(
            "INSERT INTO alert_watch (ticker, bucket, kind, active, created_at) "
            "VALUES (?, 'BUY', ?, 1, ?) "
            "ON CONFLICT(ticker) DO UPDATE SET kind = excluded.kind, active = 1",
            (ticker, kind, datetime.utcnow().isoformat() + "Z"),
        )
    return jsonify({"success": True})


@bp.route("/watches/<int:wid>", methods=["PUT"])
def update_watch(wid):
    """Move Buy↔Held, change kind, or toggle active."""
    body = request.get_json(silent=True) or {}
    sets, args = [], []
    if "bucket" in body:
        sets.append("bucket = ?")
        args.append("HELD" if str(body["bucket"]).upper() == "HELD" else "BUY")
    if "kind" in body:
        sets.append("kind = ?")
        args.append("Invest" if body["kind"] == "Invest" else "Trade")
    if "active" in body:
        sets.append("active = ?")
        args.append(1 if body["active"] else 0)
    if not sets:
        return jsonify({"success": False, "error": "nothing to update"}), 400
    args.append(wid)
    with get_db() as db:
        db.execute(f"UPDATE alert_watch SET {', '.join(sets)} WHERE id = ?", args)
    return jsonify({"success": True})


@bp.route("/watches/<int:wid>", methods=["DELETE"])
def delete_watch(wid):
    """Soft delete — deactivate, keeping the row (and its last_checked_bar).

    A hard DELETE also destroyed the dedupe watermark, so re-adding the ticker
    came back with last_checked_bar = NULL and the next check silently *armed*
    it at the current bar instead of alerting (see alert_job.run_checks). That
    made a remove/re-add round trip swallow the very signal you were chasing.
    """
    with get_db() as db:
        db.execute("UPDATE alert_watch SET active = 0 WHERE id = ?", (wid,))
    return jsonify({"success": True})


@bp.route("/seed", methods=["GET"])
def seed_suggestions():
    """Suggestions the user can confirm: open trades → Held, TRADE/INVEST
    research → Buy. Excludes tickers already watched."""
    with get_db() as db:
        # Only active watches suppress a suggestion — a ticker you removed should
        # be offered again (re-adding it revives the row, watermark intact).
        watched = {r["ticker"] for r in
                   db.execute("SELECT ticker FROM alert_watch WHERE active = 1").fetchall()}
        held = db.execute(
            "SELECT DISTINCT ticker FROM trades WHERE exit_date IS NULL"
        ).fetchall()
        buy = db.execute(
            "SELECT ticker, decision FROM researched_stocks "
            "WHERE decision IN ('TRADE', 'INVEST') ORDER BY updated_at DESC"
        ).fetchall()
    held_s = [r["ticker"].upper() for r in held if r["ticker"].upper() not in watched]
    seen = set(held_s)
    buy_s = []
    for r in buy:
        t = (r["ticker"] or "").upper()
        if t and t not in watched and t not in seen:
            buy_s.append({"ticker": t, "kind": _kind_from_decision(r["decision"])})
            seen.add(t)
    return jsonify({"success": True, "data": {"buy": buy_s, "held": held_s}})


# ─────────────────────────── settings ───────────────────────────

@bp.route("/settings", methods=["GET"])
def get_settings():
    return jsonify({"success": True, "data": {
        "ntfy_server": get_setting("ntfy_server", "https://ntfy.sh"),
        "ntfy_topic": get_setting("ntfy_topic", ""),
        "alert_enabled": get_setting("alert_enabled", False),
        "alert_check_time": get_setting("alert_check_time", "16:20"),
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
