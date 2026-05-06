from flask import Blueprint, request, jsonify
from db import get_sm_db

bp = Blueprint("smart_money", __name__)


def _classify(curr_shares, prev_shares, curr_weight, prev_weight):
    if prev_shares is None:
        return "New", None
    cw = curr_weight or 0
    pw = prev_weight or 0
    wc = cw - pw
    if abs(wc) >= 0.005:
        return ("Increased" if wc > 0 else "Decreased"), wc
    if curr_shares != prev_shares:
        return ("Increased" if curr_shares > prev_shares else "Decreased"), wc
    return "Unchanged", wc


@bp.route("/query/<ticker>", methods=["GET"])
def query_ticker(ticker):
    ticker = ticker.upper()
    limit_arg = request.args.get("limit")
    limit = int(limit_arg) if limit_arg and limit_arg.isdigit() else None
    with get_sm_db() as sm:
        row = sm.execute(
            "SELECT MAX(report_period) AS q FROM holdings WHERE ticker = ?", (ticker,)
        ).fetchone()
        if not row or not row["q"]:
            return jsonify({"success": True, "data": {"holders": [], "exited": [], "quarter": None}})
        target_q = row["q"]
        prev_row = sm.execute(
            "SELECT MAX(report_period) AS q FROM holdings WHERE ticker = ? AND report_period < ?",
            (ticker, target_q),
        ).fetchone()
        prev_q = prev_row["q"] if prev_row else None

        rows = sm.execute("""
            SELECT g.name, g.firm,
                   h.shares, h.value_usd, h.portfolio_weight,
                   hp.shares AS prev_shares,
                   hp.portfolio_weight AS prev_weight
            FROM holdings h
            JOIN gurus g ON g.id = h.guru_id
            LEFT JOIN holdings hp ON hp.guru_id = h.guru_id
                AND hp.cusip = h.cusip
                AND hp.report_period = ?
                AND COALESCE(hp.put_call, '') = COALESCE(h.put_call, '')
            WHERE h.ticker = ? AND h.report_period = ?
            ORDER BY h.portfolio_weight DESC
        """, (prev_q, ticker, target_q)).fetchall()

        exited = []
        if prev_q:
            exited = sm.execute("""
                SELECT g.name, g.firm,
                       hp.shares AS prev_shares,
                       hp.value_usd AS prev_value,
                       hp.portfolio_weight AS prev_weight
                FROM holdings hp
                JOIN gurus g ON g.id = hp.guru_id
                LEFT JOIN holdings h ON h.guru_id = hp.guru_id
                    AND h.cusip = hp.cusip
                    AND h.report_period = ?
                    AND COALESCE(h.put_call, '') = COALESCE(hp.put_call, '')
                WHERE hp.ticker = ? AND hp.report_period = ?
                  AND h.id IS NULL
                ORDER BY hp.portfolio_weight DESC
            """, (target_q, ticker, prev_q)).fetchall()

    holders = []
    for r in rows:
        status, wc = _classify(r["shares"], r["prev_shares"], r["portfolio_weight"], r["prev_weight"])
        holders.append({
            "name": r["name"], "firm": r["firm"],
            "shares": r["shares"], "value_usd": r["value_usd"],
            "weight": r["portfolio_weight"],
            "weight_change": wc, "status": status,
        })

    exited_list = [{
        "name": e["name"], "firm": e["firm"],
        "prev_shares": e["prev_shares"], "prev_weight": e["prev_weight"],
        "weight_change": -(e["prev_weight"] or 0),
        "status": "Exited",
    } for e in exited]

    if limit is not None:
        holders = holders[:limit]
        exited_list = exited_list[:limit]

    return jsonify({"success": True, "data": {
        "ticker": ticker, "quarter": target_q, "prev_quarter": prev_q,
        "holders": holders, "exited": exited_list,
    }})


@bp.route("/guru/<path:guru_name>", methods=["GET"])
def guru_portfolio(guru_name):
    with get_sm_db() as sm:
        guru = sm.execute(
            "SELECT id, name, firm FROM gurus WHERE name LIKE ? LIMIT 1",
            (f"%{guru_name}%",),
        ).fetchone()
        if not guru:
            return jsonify({"success": True, "data": None})
        row = sm.execute(
            "SELECT MAX(report_period) AS q FROM holdings WHERE guru_id = ?", (guru["id"],)
        ).fetchone()
        if not row or not row["q"]:
            return jsonify({"success": True, "data": {"guru": dict(guru), "quarter": None, "holdings": []}})
        target_q = row["q"]
        prev_row = sm.execute(
            "SELECT MAX(report_period) AS q FROM holdings WHERE guru_id = ? AND report_period < ?",
            (guru["id"], target_q),
        ).fetchone()
        prev_q = prev_row["q"] if prev_row else None

        rows = sm.execute("""
            SELECT h.ticker, h.issuer, h.cusip,
                   h.shares, h.value_usd, h.portfolio_weight,
                   hp.shares AS prev_shares,
                   hp.portfolio_weight AS prev_weight
            FROM holdings h
            LEFT JOIN holdings hp ON hp.guru_id = h.guru_id
                AND hp.cusip = h.cusip
                AND hp.report_period = ?
                AND COALESCE(hp.put_call, '') = COALESCE(h.put_call, '')
            WHERE h.guru_id = ? AND h.report_period = ?
            ORDER BY h.portfolio_weight DESC
        """, (prev_q, guru["id"], target_q)).fetchall()

    holdings = []
    for r in rows:
        status, _wc = _classify(r["shares"], r["prev_shares"], r["portfolio_weight"], r["prev_weight"])
        holdings.append({
            "ticker": r["ticker"] or r["cusip"], "issuer": r["issuer"],
            "shares": r["shares"], "value_usd": r["value_usd"],
            "weight": r["portfolio_weight"], "status": status,
        })

    return jsonify({"success": True, "data": {
        "guru": dict(guru), "quarter": target_q, "holdings": holdings,
    }})


@bp.route("/top", methods=["GET"])
def top_held():
    limit = int(request.args.get("limit", 30))
    with get_sm_db() as sm:
        row = sm.execute("SELECT MAX(report_period) AS q FROM holdings").fetchone()
        if not row or not row["q"]:
            return jsonify({"success": True, "data": {"quarter": None, "holdings": []}})
        q = row["q"]
        rows = sm.execute("""
            SELECT COALESCE(h.ticker, h.cusip) AS ticker,
                   h.issuer,
                   COUNT(DISTINCT h.guru_id) AS num_gurus,
                   SUM(h.value_usd) AS total_value,
                   AVG(h.portfolio_weight) AS avg_weight,
                   MAX(h.portfolio_weight) AS max_weight
            FROM holdings h
            WHERE h.report_period = ?
            GROUP BY COALESCE(h.ticker, h.cusip)
            ORDER BY num_gurus DESC, avg_weight DESC
            LIMIT ?
        """, (q, limit)).fetchall()
    return jsonify({"success": True, "data": {"quarter": q, "holdings": [dict(r) for r in rows]}})


@bp.route("/gurus", methods=["GET"])
def list_gurus():
    with get_sm_db() as sm:
        rows = sm.execute(
            "SELECT id, name, firm, cik, active FROM gurus WHERE active = 1 ORDER BY name"
        ).fetchall()
    return jsonify({"success": True, "data": [dict(r) for r in rows]})
