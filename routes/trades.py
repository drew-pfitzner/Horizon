from datetime import datetime, date
from collections import defaultdict
from flask import Blueprint, request, jsonify
from db import get_db, get_setting

bp = Blueprint("trades", __name__)


def _portfolio_pos_pct(entry_price, shares, currency):
    """Compute position size % vs configured portfolio, in base currency."""
    if not entry_price or not shares:
        return None
    portfolio = get_setting("portfolio", {"value": 0, "currency": "AUD"}) or {}
    try:
        base_val = float(portfolio.get("value") or 0)
    except (TypeError, ValueError):
        base_val = 0
    if base_val <= 0:
        return None
    base_cur = (portfolio.get("currency") or "AUD").upper()
    from routes.settings import get_fx_rate
    fx = get_fx_rate((currency or "USD").upper(), base_cur)
    if fx is None:
        return None
    return round(entry_price * shares * fx / base_val * 100, 2)


def recompute_open_positions():
    portfolio = get_setting("portfolio", {"value": 0, "currency": "AUD"}) or {}
    try:
        base_val = float(portfolio.get("value") or 0)
    except (TypeError, ValueError):
        base_val = 0
    if base_val <= 0:
        return 0
    count = 0
    with get_db() as db:
        rows = db.execute(
            "SELECT id, entry_price, shares, currency FROM trades "
            "WHERE exit_date IS NULL OR exit_date = ''"
        ).fetchall()
        for r in rows:
            pct = _portfolio_pos_pct(r["entry_price"], r["shares"], r["currency"])
            if pct is not None:
                db.execute("UPDATE trades SET position_size_pct=? WHERE id=?", (pct, r["id"]))
                count += 1
    return count


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
    auto_pos = _portfolio_pos_pct(entry_price, shares, currency)
    if auto_pos is not None:
        pos_pct = auto_pos
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

        if not ex.get("exit_date"):
            auto_pos = _portfolio_pos_pct(ex.get("entry_price"), ex.get("shares"), ex.get("currency"))
            if auto_pos is not None:
                ex["position_size_pct"] = auto_pos

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

    portfolio = get_setting("portfolio", {"value": 0, "currency": "AUD"}) or {}
    try:
        portfolio_value = float(portfolio.get("value") or 0)
    except (TypeError, ValueError):
        portfolio_value = 0.0
    portfolio_currency = (portfolio.get("currency") or "AUD").upper()
    from routes.settings import get_fx_rate

    by_month = defaultdict(lambda: {
        "open_count": 0, "closed_count": 0, "wins": 0, "losses": 0,
        "total_pl": 0.0, "total_roi": 0.0, "trades": [],
    })

    overall = {"open": 0, "closed": 0, "wins": 0, "losses": 0,
               "total_pl": 0.0, "avg_roi": 0.0, "win_rate": 0.0,
               "total_pl_base": 0.0, "portfolio_value": round(portfolio_value, 2),
               "portfolio_currency": portfolio_currency,
               "return_on_capital": None,   # year-scoped: selected-year realized P/L ÷ portfolio
               "cagr": None}                # all-time compound annual growth of implied equity

    closed_rois = []
    year_pl_base = 0.0        # realized P/L (base ccy) for trades entered in `year`
    first_entry = None        # earliest entry date across all trades (CAGR span start)
    for t in trades:
        # base-currency realized P/L for this trade (computed once)
        pl_base = None
        if t.get("exit_date") and t.get("pl_dollar") is not None:
            fx = get_fx_rate((t.get("currency") or "USD").upper(), portfolio_currency)
            if fx is not None:
                pl_base = t["pl_dollar"] * fx

        if t.get("entry_date"):
            if first_entry is None or t["entry_date"] < first_entry:
                first_entry = t["entry_date"]
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
                    if pl_base is not None:
                        year_pl_base += pl_base
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
                if pl_base is not None:
                    overall["total_pl_base"] += pl_base
            if t.get("roi_pct") is not None:
                closed_rois.append(t["roi_pct"])
        else:
            overall["open"] += 1

    if closed_rois:
        overall["avg_roi"] = round(sum(closed_rois) / len(closed_rois), 2)
    if overall["wins"] + overall["losses"] > 0:
        overall["win_rate"] = round(overall["wins"] / (overall["wins"] + overall["losses"]) * 100, 1)
    overall["total_pl"] = round(overall["total_pl"], 2)
    overall["total_pl_base"] = round(overall["total_pl_base"], 2)
    overall["year_pl_base"] = round(year_pl_base, 2)

    # Return on Capital (selected year): realized P/L this year vs current account size
    if portfolio_value > 0:
        overall["return_on_capital"] = round(year_pl_base / portfolio_value * 100, 2)

    # All-time CAGR: annualized growth of implied starting equity → current portfolio.
    # Starting equity is inferred as current value minus all realized gains (no deposit
    # history is tracked), annualized over the span since the first trade entry.
    start_equity = portfolio_value - overall["total_pl_base"]
    if portfolio_value > 0 and start_equity > 0 and first_entry:
        try:
            span_days = (date.today() - date.fromisoformat(first_entry)).days
        except (ValueError, TypeError):
            span_days = 0
        years_elapsed = span_days / 365.25
        if years_elapsed >= 0.5:  # too short a span makes annualizing meaningless
            overall["cagr"] = round(((portfolio_value / start_equity) ** (1 / years_elapsed) - 1) * 100, 2)

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
