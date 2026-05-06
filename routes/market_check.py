from datetime import datetime, date
from flask import Blueprint, request, jsonify
from db import get_db, get_setting


bp = Blueprint("market_check", __name__)


# Crash/recession color rules — fixed (max of the two indicators).
def _stl_color(v):
    if v is None:
        return None
    if v <= -1: return "green"
    if v < 0:   return "blue"
    if v < 1:   return "orange"
    return "red"


def _vix_color(v):
    if v is None:
        return None
    if v <= 25: return "green"
    if v < 30:  return "orange"
    return "red"


def _crash_risk(stl, vix):
    colors = [c for c in (_stl_color(stl), _vix_color(vix)) if c is not None]
    if not colors:
        return None
    if "red" in colors:    return "NO_TRADE"
    if "orange" in colors: return "CAUTION"
    return "OK"


def _score(v, low, mid):
    if v is None:
        return None
    if v <= low: return 1
    if v < mid:  return 2
    return 3


def compute_gate(stl, vix, rsi, sto, s5fi, fg):
    crash_risk = _crash_risk(stl, vix)

    if any(x is None for x in (rsi, sto, s5fi, fg)):
        return crash_risk, None, None

    t = get_setting("pullback_thresholds") or {}
    rsi_t  = t.get("rsi", {"low": 30, "mid": 60})
    sto_t  = t.get("stochastic", {"low": 20, "mid": 80})
    s5_t   = t.get("s5fi", {"low": 40, "mid": 70})
    fg_t   = t.get("fear_greed", {"low": 45, "mid": 55})

    worst = max(
        _score(rsi, rsi_t["low"], rsi_t["mid"]),
        _score(sto, sto_t["low"], sto_t["mid"]),
        _score(s5fi, s5_t["low"], s5_t["mid"]),
        _score(fg, fg_t["low"], fg_t["mid"]),
    )
    table = {1: ("LOW", 2.0), 2: ("MED", 1.5), 3: ("HIGH", 1.0)}
    level, pct = table[worst]
    return crash_risk, level, pct


def can_trade(crash_risk):
    return crash_risk == "OK"


def row_to_dict(r):
    if r is None:
        return None
    d = dict(r)
    d["can_trade"] = can_trade(d.get("crash_risk"))
    return d


@bp.route("/today", methods=["GET"])
def get_today():
    today = date.today().isoformat()
    with get_db() as db:
        row = db.execute("SELECT * FROM market_check WHERE date = ?", (today,)).fetchone()
    return jsonify({"success": True, "data": row_to_dict(row), "date": today})


@bp.route("/history", methods=["GET"])
def history():
    limit = int(request.args.get("limit", 30))
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM market_check ORDER BY date DESC LIMIT ?", (limit,)
        ).fetchall()
    return jsonify({"success": True, "data": [row_to_dict(r) for r in rows]})


@bp.route("", methods=["POST"])
def upsert():
    p = request.get_json(force=True)
    today = p.get("date") or date.today().isoformat()
    stl = p.get("st_louis_fed")
    vix = p.get("vix")
    rsi = p.get("rsi")
    sto = p.get("stochastic")
    s5fi = p.get("s5fi")
    fg = p.get("fear_greed")
    notes = p.get("notes", "")

    crash_risk, level, pct = compute_gate(stl, vix, rsi, sto, s5fi, fg)
    now = datetime.now().isoformat(timespec="seconds")

    with get_db() as db:
        db.execute("""
            INSERT INTO market_check
                (date, st_louis_fed, vix, rsi, stochastic, s5fi, fear_greed,
                 crash_risk, position_size_level, position_size_pct, notes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                st_louis_fed=excluded.st_louis_fed,
                vix=excluded.vix,
                rsi=excluded.rsi,
                stochastic=excluded.stochastic,
                s5fi=excluded.s5fi,
                fear_greed=excluded.fear_greed,
                crash_risk=excluded.crash_risk,
                position_size_level=excluded.position_size_level,
                position_size_pct=excluded.position_size_pct,
                notes=excluded.notes,
                updated_at=excluded.updated_at
        """, (today, stl, vix, rsi, sto, s5fi, fg, crash_risk, level, pct, notes, now))
        row = db.execute("SELECT * FROM market_check WHERE date = ?", (today,)).fetchone()

    return jsonify({"success": True, "data": row_to_dict(row)})


@bp.route("/preview", methods=["POST"])
def preview():
    p = request.get_json(force=True)
    crash_risk, level, pct = compute_gate(
        p.get("st_louis_fed"), p.get("vix"), p.get("rsi"),
        p.get("stochastic"), p.get("s5fi"), p.get("fear_greed"),
    )
    return jsonify({
        "success": True,
        "data": {
            "crash_risk": crash_risk,
            "position_size_level": level,
            "position_size_pct": pct,
            "can_trade": can_trade(crash_risk),
        },
    })


@bp.route("/<date_str>", methods=["DELETE"])
def delete_row(date_str):
    with get_db() as db:
        cur = db.execute("DELETE FROM market_check WHERE date = ?", (date_str,))
    if cur.rowcount == 0:
        return jsonify({"success": False, "error": "not found"}), 404
    return jsonify({"success": True, "data": {"deleted": date_str}})
