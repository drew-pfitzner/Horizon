"""
Freedom Trader Equity Multiple valuation.

Inputs (per stock):
  - 5 years of ROE %                      (latest first: roe1 .. roe5)
  - 5 years of Dividend Payout Ratio       (decimal 0..1; latest first: payout1 .. payout5)
  - Required return %, Total Equity ($M), Shares Outstanding (M), Current Price

Per-stat (Average / Median / MOS=median*0.9) computation:
  - Normalised ROE  (%)
  - Payout          (decimal)  — corresponding stat across 5 years
  - Distributed (%) = ROE * Payout
  - Reinvested  (%) = ROE - Distributed = ROE * (1 - Payout)
  - Equity Multiplier  = (Reinvested %)^2 / 100
  - Equity Per Share   = Total Equity / Shares Outstanding
  - Valuation $        = Equity Per Share * Equity Multiplier
  - Discount %         = (Valuation - Price) / Valuation * 100

Assessment uses MOS valuation: price <= MOS => UNDERVALUED, <= median => FAIR_VALUE, else OVERVALUED.
"""

import statistics
from datetime import datetime, date
from flask import Blueprint, request, jsonify
from db import get_db


bp = Blueprint("valuation", __name__)


def _floats(vals):
    out = []
    for v in vals:
        if v is None or v == "":
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def calculate(p):
    roes = _floats([p.get(f"roe{i}") for i in range(1, 6)])
    payouts = _floats([p.get(f"payout{i}") for i in range(1, 6)])
    if not roes:
        return None, "at least one ROE year required"

    total_eq = float(p.get("total_equity_m") or 0)
    shares = float(p.get("shares_outstanding_m") or 0)
    current = float(p.get("current_price") or 0)
    if shares <= 0:
        return None, "shares outstanding required"

    eps_book = total_eq / shares  # equity per share (book value)

    roe_avg = statistics.mean(roes)
    roe_med = statistics.median(roes)
    roe_mos = roe_med * 0.90

    if payouts:
        payout_avg = statistics.mean(payouts)
        payout_med = statistics.median(payouts)
    else:
        payout_avg = 0.0
        payout_med = 0.0
    payout_mos = payout_med * 0.90

    def distrib(roe, payout):
        return roe * payout

    def reinv(roe, payout):
        return roe * (1.0 - payout)

    def mult(reinvested):
        return (reinvested ** 2) / 100.0

    def disc(v):
        return ((v - current) / v * 100) if v else 0.0

    cols = {}
    for name, roe, payout in (
        ("avg",    roe_avg, payout_avg),
        ("median", roe_med, payout_med),
        ("mos",    roe_mos, payout_mos),
    ):
        d = distrib(roe, payout)
        r = reinv(roe, payout)
        m = mult(r)
        v = eps_book * m
        cols[name] = {
            "roe": roe, "payout": payout,
            "distributed": d, "reinvested": r,
            "multiplier": m, "valuation": v, "discount_pct": disc(v),
        }

    if cols["mos"]["valuation"] > 0 and current <= cols["mos"]["valuation"]:
        assessment = "UNDERVALUED"
    elif cols["median"]["valuation"] > 0 and current <= cols["median"]["valuation"]:
        assessment = "FAIR_VALUE"
    else:
        assessment = "OVERVALUED"

    return {
        "equity_per_share": round(eps_book, 4),
        "roe_avg": round(roe_avg, 4),
        "roe_median": round(roe_med, 4),
        "roe_mos": round(roe_mos, 4),
        "payout_avg": round(payout_avg, 6),
        "payout_median": round(payout_med, 6),
        "payout_mos": round(payout_mos, 6),
        "distributed_avg": round(cols["avg"]["distributed"], 4),
        "distributed_median": round(cols["median"]["distributed"], 4),
        "distributed_mos": round(cols["mos"]["distributed"], 4),
        "reinvested_avg": round(cols["avg"]["reinvested"], 4),
        "reinvested_median": round(cols["median"]["reinvested"], 4),
        "reinvested_mos": round(cols["mos"]["reinvested"], 4),
        "multiplier_avg": round(cols["avg"]["multiplier"], 4),
        "multiplier_median": round(cols["median"]["multiplier"], 4),
        "multiplier_mos": round(cols["mos"]["multiplier"], 4),
        "valuation_avg": round(cols["avg"]["valuation"], 4),
        "valuation_median": round(cols["median"]["valuation"], 4),
        "valuation_mos": round(cols["mos"]["valuation"], 4),
        "discount_avg_pct": round(cols["avg"]["discount_pct"], 2),
        "discount_median_pct": round(cols["median"]["discount_pct"], 2),
        "discount_mos_pct": round(cols["mos"]["discount_pct"], 2),
        "assessment": assessment,
    }, None


@bp.route("/preview", methods=["POST"])
def preview():
    p = request.get_json(force=True)
    result, err = calculate(p)
    if err:
        return jsonify({"success": False, "error": err}), 400
    return jsonify({"success": True, "data": result})


@bp.route("", methods=["POST"])
def save():
    p = request.get_json(force=True)
    result, err = calculate(p)
    if err:
        return jsonify({"success": False, "error": err}), 400

    ticker = (p.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify({"success": False, "error": "ticker required"}), 400

    now = datetime.now().isoformat(timespec="seconds")
    vdate = p.get("valuation_date") or date.today().isoformat()

    with get_db() as db:
        cur = db.execute("""
            INSERT INTO valuations (
                ticker, company_name, valuation_date, current_price,
                roe1, roe2, roe3, roe4, roe5,
                payout1, payout2, payout3, payout4, payout5,
                required_return, total_equity_m, shares_outstanding_m,
                equity_per_share,
                roe_avg, roe_median, roe_mos,
                payout_avg, payout_median, payout_mos,
                distributed_avg, distributed_median, distributed_mos,
                reinvested_avg, reinvested_median, reinvested_mos,
                multiplier_avg, multiplier_median, multiplier_mos,
                valuation_avg, valuation_median, valuation_mos,
                discount_avg_pct, discount_median_pct, discount_mos_pct,
                assessment, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?)
        """, (
            ticker, p.get("company_name") or "", vdate, p.get("current_price"),
            p.get("roe1"), p.get("roe2"), p.get("roe3"), p.get("roe4"), p.get("roe5"),
            p.get("payout1"), p.get("payout2"), p.get("payout3"), p.get("payout4"), p.get("payout5"),
            p.get("required_return") or 10.0,
            p.get("total_equity_m"), p.get("shares_outstanding_m"),
            result["equity_per_share"],
            result["roe_avg"], result["roe_median"], result["roe_mos"],
            result["payout_avg"], result["payout_median"], result["payout_mos"],
            result["distributed_avg"], result["distributed_median"], result["distributed_mos"],
            result["reinvested_avg"], result["reinvested_median"], result["reinvested_mos"],
            result["multiplier_avg"], result["multiplier_median"], result["multiplier_mos"],
            result["valuation_avg"], result["valuation_median"], result["valuation_mos"],
            result["discount_avg_pct"], result["discount_median_pct"], result["discount_mos_pct"],
            result["assessment"], now,
        ))
        vid = cur.lastrowid

        rid = p.get("research_id")
        if rid:
            db.execute(
                "UPDATE researched_stocks SET latest_valuation_id = ?, updated_at = ? WHERE id = ?",
                (vid, now, rid),
            )

        row = db.execute("SELECT * FROM valuations WHERE id = ?", (vid,)).fetchone()
    return jsonify({"success": True, "data": dict(row)})


@bp.route("/<ticker>", methods=["GET"])
def latest_for_ticker(ticker):
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM valuations WHERE ticker = ? ORDER BY created_at DESC LIMIT 1",
            (ticker.upper(),),
        ).fetchone()
    return jsonify({"success": True, "data": dict(row) if row else None})
