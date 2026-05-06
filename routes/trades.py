from datetime import datetime, date
from collections import defaultdict
from flask import Blueprint, request, jsonify
from db import get_db

bp = Blueprint("trades", __name__)


def _compute_pl(entry_price, shares, exit_price, entry_date, exit_date):
    if exit_price is None or entry_price is None or shares is None:
        return None, None, None, "HOLD"
    pl = (exit_price - entry_price) * shares
    cost = entry_price * shares
    roi = (pl / cost * 100) if cost else 0.0
    days = None
    if entry_date and exit_date:
        try:
            d1 = date.fromisoformat(entry_date)
            d2 = date.fromisoformat(exit_date)
            days = (d2 - d1).days
        except Exception:
            days = None
    win_loss = "WIN" if pl > 0 else ("LOSS" if pl < 0 else "HOLD")
    return round(pl, 2), round(roi, 4), days, win_loss


@bp.route("", methods=["GET"])
def list_trades():
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM trades ORDER BY entry_date DESC, id DESC"
        ).fetchall()
    return jsonify({"success": True, "data": [dict(r) for r in rows]})


@bp.route("", methods=["POST"])
def create():
    p = request.get_json(force=True)
    ticker = (p.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify({"success": False, "error": "ticker required"}), 400

    entry_date = p.get("entry_date") or date.today().isoformat()
    entry_price = float(p.get("entry_price") or 0)
    shares = float(p.get("shares") or 0)
    pos_pct = p.get("position_size_pct")
    strategy = p.get("strategy") or "TRADE"
    currency = (p.get("currency") or "USD").upper()
    exit_date = p.get("exit_date")
    exit_price = float(p.get("exit_price")) if p.get("exit_price") not in (None, "") else None

    pl, roi, days, win_loss = _compute_pl(entry_price, shares, exit_price, entry_date, exit_date)
    now = datetime.now().isoformat(timespec="seconds")

    with get_db() as db:
        cur = db.execute("""
            INSERT INTO trades (
                ticker, company_name, sector, industry, strategy, currency,
                entry_date, entry_price, shares, position_size_pct,
                exit_date, exit_price, pl_dollar, roi_pct, days_held, win_loss,
                notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ticker, p.get("company_name") or "", p.get("sector") or "", p.get("industry") or "",
            strategy, currency, entry_date, entry_price, shares, pos_pct,
            exit_date, exit_price, pl, roi, days, win_loss,
            p.get("notes") or "", now, now,
        ))
        tid = cur.lastrowid
        row = db.execute("SELECT * FROM trades WHERE id = ?", (tid,)).fetchone()
    return jsonify({"success": True, "data": dict(row)})


@bp.route("/<int:tid>", methods=["PUT"])
def update(tid):
    p = request.get_json(force=True)
    now = datetime.now().isoformat(timespec="seconds")

    with get_db() as db:
        existing = db.execute("SELECT * FROM trades WHERE id = ?", (tid,)).fetchone()
        if not existing:
            return jsonify({"success": False, "error": "not found"}), 404
        ex = dict(existing)

        for k in ("ticker", "company_name", "sector", "industry", "strategy",
                  "currency", "entry_date", "exit_date", "notes"):
            if k in p and p[k] is not None:
                ex[k] = p[k]
        if "currency" in p and p["currency"]:
            ex["currency"] = str(ex["currency"]).upper()
        for k in ("entry_price", "exit_price", "shares", "position_size_pct"):
            if k in p and p[k] not in (None, ""):
                ex[k] = float(p[k])
            elif k == "exit_price" and "exit_price" in p and p[k] in (None, ""):
                ex[k] = None

        pl, roi, days, win_loss = _compute_pl(
            ex.get("entry_price"), ex.get("shares"),
            ex.get("exit_price"), ex.get("entry_date"), ex.get("exit_date"),
        )
        ex["pl_dollar"], ex["roi_pct"], ex["days_held"], ex["win_loss"] = pl, roi, days, win_loss

        db.execute("""
            UPDATE trades SET
                ticker=?, company_name=?, sector=?, industry=?, strategy=?, currency=?,
                entry_date=?, entry_price=?, shares=?, position_size_pct=?,
                exit_date=?, exit_price=?, pl_dollar=?, roi_pct=?, days_held=?, win_loss=?,
                notes=?, updated_at=?
            WHERE id = ?
        """, (
            ex["ticker"], ex["company_name"], ex["sector"], ex["industry"], ex["strategy"],
            ex.get("currency") or "USD",
            ex["entry_date"], ex["entry_price"], ex["shares"], ex["position_size_pct"],
            ex["exit_date"], ex["exit_price"], ex["pl_dollar"], ex["roi_pct"], ex["days_held"],
            ex["win_loss"], ex["notes"], now, tid,
        ))
        row = db.execute("SELECT * FROM trades WHERE id = ?", (tid,)).fetchone()
    return jsonify({"success": True, "data": dict(row)})


@bp.route("/<int:tid>", methods=["DELETE"])
def delete(tid):
    with get_db() as db:
        db.execute("DELETE FROM trades WHERE id = ?", (tid,))
    return jsonify({"success": True})


@bp.route("/performance", methods=["GET"])
def performance():
    year = request.args.get("year", str(date.today().year))

    with get_db() as db:
        rows = db.execute("SELECT * FROM trades").fetchall()
    trades = [dict(r) for r in rows]

    by_month = defaultdict(lambda: {
        "open_count": 0, "closed_count": 0, "wins": 0, "losses": 0,
        "total_pl": 0.0, "total_roi": 0.0, "trades": [],
    })

    overall = {"open": 0, "closed": 0, "wins": 0, "losses": 0,
               "total_pl": 0.0, "avg_roi": 0.0, "win_rate": 0.0}

    closed_rois = []
    for t in trades:
        if t.get("entry_date"):
            ent_year = t["entry_date"][:4]
            ent_month = t["entry_date"][5:7]
            if ent_year == year:
                m = by_month[ent_month]
                if t.get("exit_date"):
                    m["closed_count"] += 1
                    if t.get("win_loss") == "WIN":
                        m["wins"] += 1
                    elif t.get("win_loss") == "LOSS":
                        m["losses"] += 1
                    if t.get("pl_dollar") is not None:
                        m["total_pl"] += t["pl_dollar"]
                    if t.get("roi_pct") is not None:
                        m["total_roi"] += t["roi_pct"]
                else:
                    m["open_count"] += 1
                m["trades"].append({"ticker": t["ticker"], "id": t["id"],
                                     "win_loss": t["win_loss"], "roi_pct": t["roi_pct"]})

        if t.get("exit_date"):
            overall["closed"] += 1
            if t.get("win_loss") == "WIN":
                overall["wins"] += 1
            elif t.get("win_loss") == "LOSS":
                overall["losses"] += 1
            if t.get("pl_dollar") is not None:
                overall["total_pl"] += t["pl_dollar"]
            if t.get("roi_pct") is not None:
                closed_rois.append(t["roi_pct"])
        else:
            overall["open"] += 1

    if closed_rois:
        overall["avg_roi"] = round(sum(closed_rois) / len(closed_rois), 2)
    if overall["wins"] + overall["losses"] > 0:
        overall["win_rate"] = round(overall["wins"] / (overall["wins"] + overall["losses"]) * 100, 1)
    overall["total_pl"] = round(overall["total_pl"], 2)

    months = []
    for i in range(1, 13):
        mm = f"{i:02d}"
        m = by_month.get(mm, {"open_count": 0, "closed_count": 0, "wins": 0,
                              "losses": 0, "total_pl": 0.0, "total_roi": 0.0, "trades": []})
        months.append({
            "month": mm,
            "open_count": m["open_count"],
            "closed_count": m["closed_count"],
            "wins": m["wins"],
            "losses": m["losses"],
            "total_pl": round(m["total_pl"], 2),
            "total_roi": round(m["total_roi"], 2),
        })

    return jsonify({"success": True, "data": {"year": year, "months": months, "overall": overall}})
