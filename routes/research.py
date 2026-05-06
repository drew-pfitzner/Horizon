from datetime import datetime, date
from flask import Blueprint, request, jsonify
from db import get_db

bp = Blueprint("research", __name__)


FUND_FIELDS = [
    "f_roa", "f_roe", "f_roi", "f_npm",
    "f_eps_5yr", "f_eps_1yr", "f_eps_next",
    "f_sales_5yr", "f_current_ratio", "f_debt_equity",
]
ALL_FLAGS = FUND_FIELDS + [
    "market_cap_ok", "sm_holding_5pct", "sm_top3_increasing",
    "liquidity_ok", "tech_rsi_ok", "tech_sto_ok", "tech_cross_ok",
    "price_below_mos",
]


def _to_int(v):
    return 1 if v else 0


def _payload_to_args(p, ticker_required=True):
    ticker = (p.get("ticker") or "").strip().upper()
    if ticker_required and not ticker:
        return None, "ticker required"

    flags = {f: _to_int(p.get(f)) for f in ALL_FLAGS}
    fund_score = sum(flags[f] for f in FUND_FIELDS)
    return {
        "ticker": ticker,
        "company_name": p.get("company_name") or "",
        "date_researched": p.get("date_researched") or date.today().isoformat(),
        "fundamentals_score": fund_score,
        "decision": p.get("decision") or "NO_ACTION",
        "notes": p.get("notes") or "",
        **flags,
    }, None


@bp.route("", methods=["GET"])
def list_research():
    with get_db() as db:
        rows = db.execute("""
            SELECT r.*, v.assessment as valuation_assessment, v.current_price, v.valuation_median
            FROM researched_stocks r
            LEFT JOIN valuations v ON v.id = r.latest_valuation_id
            ORDER BY r.updated_at DESC, r.id DESC
        """).fetchall()
    return jsonify({"success": True, "data": [dict(r) for r in rows]})


@bp.route("/<int:rid>", methods=["GET"])
def get_one(rid):
    with get_db() as db:
        row = db.execute("""
            SELECT r.*, v.assessment as valuation_assessment, v.current_price, v.valuation_median
            FROM researched_stocks r
            LEFT JOIN valuations v ON v.id = r.latest_valuation_id
            WHERE r.id = ?
        """, (rid,)).fetchone()
    if not row:
        return jsonify({"success": False, "error": "not found"}), 404
    return jsonify({"success": True, "data": dict(row)})


@bp.route("", methods=["POST"])
def create():
    p = request.get_json(force=True)
    args, err = _payload_to_args(p)
    if err:
        return jsonify({"success": False, "error": err}), 400
    now = datetime.now().isoformat(timespec="seconds")

    cols = ["ticker", "company_name", "date_researched", "fundamentals_score",
            "decision", "notes", *ALL_FLAGS, "created_at", "updated_at"]
    placeholders = ", ".join(["?"] * len(cols))
    values = [args[c] if c in args else 0 for c in cols[:-2]] + [now, now]

    with get_db() as db:
        cur = db.execute(
            f"INSERT INTO researched_stocks ({', '.join(cols)}) VALUES ({placeholders})",
            values,
        )
        rid = cur.lastrowid
        row = db.execute("SELECT * FROM researched_stocks WHERE id = ?", (rid,)).fetchone()
    return jsonify({"success": True, "data": dict(row)})


@bp.route("/<int:rid>", methods=["PUT"])
def update(rid):
    p = request.get_json(force=True)
    args, err = _payload_to_args(p, ticker_required=False)
    if err:
        return jsonify({"success": False, "error": err}), 400
    now = datetime.now().isoformat(timespec="seconds")

    set_cols = ["company_name", "date_researched", "fundamentals_score", "decision", "notes", *ALL_FLAGS]
    if args["ticker"]:
        set_cols.insert(0, "ticker")
    set_clause = ", ".join(f"{c} = ?" for c in set_cols) + ", updated_at = ?"
    values = [args[c] for c in set_cols] + [now]

    with get_db() as db:
        db.execute(f"UPDATE researched_stocks SET {set_clause} WHERE id = ?", [*values, rid])
        row = db.execute("SELECT * FROM researched_stocks WHERE id = ?", (rid,)).fetchone()
    if not row:
        return jsonify({"success": False, "error": "not found"}), 404
    return jsonify({"success": True, "data": dict(row)})


@bp.route("/<int:rid>", methods=["DELETE"])
def delete(rid):
    with get_db() as db:
        db.execute("DELETE FROM researched_stocks WHERE id = ?", (rid,))
    return jsonify({"success": True})
