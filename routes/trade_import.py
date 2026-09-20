"""Paste an IBKR CSV, see what it would change, then commit it.

Two endpoints, one plan. `preview` parses the CSV and returns the plan without
touching anything; `apply` re-parses the *same* CSV server-side, rebuilds the
same plan with the human's answers folded in, and writes only the actions that
were accepted. Nothing numeric round-trips through the browser — the client
sends back choices, not figures.

The planning itself lives in `ibkr_import.py`, which knows nothing about SQL.
"""

from datetime import datetime

from flask import Blueprint, request, jsonify

import ibkr_import as imp
from db import get_db, get_setting, set_setting
from routes.trades import _compute_pl, _portfolio_pos_pct, commission_pct

bp = Blueprint("trade_import", __name__)

# Columns of `trades` the importer owns. Everything else on a row it adopts —
# notes, strategy, sector — is left exactly as the user left it.
_DERIVED_COLUMNS = ("entry_date", "entry_price", "shares", "entry_fee",
                    "exit_date", "exit_price", "exit_fee")


def _load_context(tickers):
    """Everything the planner needs to know about the current state of the log."""
    with get_db() as db:
        trades = [dict(r) for r in db.execute("SELECT * FROM trades").fetchall()]
        counts = {r["trade_id"]: r["n"] for r in db.execute(
            "SELECT trade_id, COUNT(*) AS n FROM trade_fills "
            "WHERE trade_id IS NOT NULL GROUP BY trade_id").fetchall()}
        # Every fingerprint on file counts as seen — including the ones filed
        # under 'ignored', which is how a sale you told the importer to leave
        # out stops asking again on the next statement.
        known = {r["fill_key"] for r in
                 db.execute("SELECT fill_key FROM trade_fills").fetchall()}
        ledger = []
        if tickers:
            marks = ",".join("?" * len(tickers))
            ledger = [dict(r) for r in db.execute(
                f"SELECT * FROM trade_fills WHERE ticker IN ({marks}) "
                "AND source != 'ignored'", tuple(tickers)).fetchall()]
    for t in trades:
        t["fill_count"] = counts.get(t["id"], 0)
    for f in ledger:
        f.setdefault("row", -5)
    return trades, known, ledger


def _plan_from_request(payload):
    """Parse + plan. Shared by preview and apply so the two can't drift."""
    parsed = imp.parse_csv(payload.get("csv") or "")
    tickers = sorted({f["ticker"] for f in parsed["fills"]})
    trades, known, ledger = _load_context(tickers)
    parsed["ledger_fills"] = ledger
    plan = imp.build_plan(parsed, trades, known,
                          commission_pct=commission_pct(),
                          resolutions=payload.get("resolutions") or {})
    _annotate_portfolio(plan)
    return plan


def _annotate_portfolio(plan):
    """Hang the stored portfolio value alongside the statement's, so the panel
    can show the change before anything is written. An Activity Statement states
    the account's NAV; the other report shapes don't, and then there's no card."""
    found = plan.get("portfolio")
    if not found:
        return
    stored = get_setting("portfolio") or {}
    found["currency"] = found.get("currency") or stored.get("currency") or "AUD"
    found["stored"] = {"value": stored.get("value"), "currency": stored.get("currency")}


@bp.route("/preview", methods=["POST"])
def preview():
    payload = request.get_json(force=True) or {}
    try:
        plan = _plan_from_request(payload)
    except imp.ImportError_ as e:
        return jsonify({"success": False, "error": str(e)}), 400
    return jsonify({"success": True, "data": imp.strip_internals(plan)})


@bp.route("/apply", methods=["POST"])
def apply():
    payload = request.get_json(force=True) or {}
    try:
        plan = _plan_from_request(payload)
    except imp.ImportError_ as e:
        return jsonify({"success": False, "error": str(e)}), 400

    accept = payload.get("accept")
    resolutions = payload.get("resolutions") or {}
    strategies = payload.get("strategies") or {}
    wanted = {a["key"] for a in plan["actions"]
              if a["action"] in ("create", "update")}
    if accept is not None:
        wanted &= set(accept)

    # Deliberate "leave it out" answers are recorded too, as fills with no trade
    # behind them, so the same sale doesn't raise the same question every month.
    declined = [a for a in plan["actions"]
                if a["action"] == "skip"
                and (resolutions.get(a["key"]) or {}).get("mode") == "ignore"]

    blocked = [a["key"] for a in plan["actions"]
               if a["action"] == "ambiguous" and a["key"] in (accept or [])]
    if blocked:
        return jsonify({"success": False,
                        "error": f"Still needs an answer: {', '.join(blocked)}"}), 400

    now = datetime.now().isoformat(timespec="seconds")
    created = updated = fills_added = 0
    touched = []

    # The account's NAV goes in first, so the position sizes worked out for the
    # rows below are measured against the portfolio the statement describes.
    portfolio = _save_portfolio(plan) if payload.get("update_portfolio") else None

    with get_db() as db:
        for action in plan["actions"]:
            if action["key"] not in wanted:
                continue
            c, u, f, names = _apply_action(
                db, action, strategies.get(action["key"]) or "TRADE", now)
            created += c
            updated += u
            fills_added += f
            touched.extend(names)

        for action in declined:
            for fill in action.get("_fills", []):
                if fill.get("source") != "ibkr":
                    continue
                db.execute(
                    "INSERT OR IGNORE INTO trade_fills (trade_id, fill_key, "
                    "position_key, ticker, trade_date, side, qty, price, "
                    "commission, currency, description, source, imported_at) "
                    "VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ignored', ?)",
                    (fill["fill_key"], action.get("position_key"), fill["ticker"],
                     fill["trade_date"], fill["side"], fill["qty"], fill["price"],
                     fill.get("commission"), fill.get("currency"),
                     fill.get("description"), now),
                )

        db.execute(
            "INSERT INTO trade_imports (imported_at, account, period_start, "
            "period_end, fills_new, trades_created, trades_updated, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (now, plan.get("account"), plan["period"].get("start"),
             plan["period"].get("end"), fills_added, created, updated,
             payload.get("note") or ""),
        )

    return jsonify({"success": True, "data": {
        "created": created, "updated": updated, "fills_added": fills_added,
        "tickers": sorted(set(touched)),
        "period": plan["period"],
        "portfolio": portfolio,
    }})


def _save_portfolio(plan):
    """Write the statement's NAV into the `portfolio` setting the position
    sizing reads. Only the value and its currency are ours; anything else stored
    under the key is left alone."""
    found = plan.get("portfolio")
    if not found or found.get("value") is None:
        return None
    stored = dict(get_setting("portfolio") or {})
    stored["value"] = found["value"]
    stored["currency"] = found.get("currency") or stored.get("currency") or "AUD"
    set_setting("portfolio", stored)
    return {"value": stored["value"], "currency": stored["currency"],
            "as_of": found.get("as_of")}


def _apply_action(db, action, strategy, now):
    """Write one position group: upsert its 1–2 rows, then file its fills."""
    created = updated = fills_added = 0
    pkey = action.get("position_key")
    target_ids = []

    for target in action.get("targets", []):
        derived = target["derived"]
        if target.get("trade_id") is None:
            tid = _insert_trade(db, derived, strategy, pkey, now)
            created += 1
        else:
            tid = target["trade_id"]
            if target.get("diff"):
                _update_trade(db, tid, derived, pkey, now)
                updated += 1
            else:
                db.execute("UPDATE trades SET import_key=? WHERE id=?", (pkey, tid))
        target_ids.append(tid)

    # The primary row owns the fills. Prefer the open half of a split so a later
    # add lands where the position actually lives.
    primary = None
    for target, tid in zip(action.get("targets", []), target_ids):
        if target["slot"] == "open":
            primary = tid
            break
    if primary is None and target_ids:
        primary = target_ids[0]

    # A row this position used to occupy but no longer needs — a split that has
    # since gone flat, say. Move its fills across before dropping it, or the
    # cascade would take the ledger with it and the next import would rebuild
    # the position from nothing.
    for orphan in action.get("orphaned_trade_ids", []):
        if orphan in target_ids:
            continue
        db.execute("UPDATE trade_fills SET trade_id=? WHERE trade_id=?", (primary, orphan))
        db.execute("DELETE FROM trades WHERE id=?", (orphan,))

    for fill in action.get("_fills", []):
        if fill.get("source") == "manual":
            continue          # a row's own baseline is not a broker fill
        cur = db.execute(
            "INSERT OR IGNORE INTO trade_fills (trade_id, fill_key, position_key, "
            "ticker, trade_date, side, qty, price, commission, currency, "
            "description, source, imported_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (primary, fill["fill_key"], pkey, fill["ticker"], fill["trade_date"],
             fill["side"], fill["qty"], fill["price"], fill.get("commission"),
             fill.get("currency"), fill.get("description"), fill.get("source"), now),
        )
        if cur.rowcount:
            fills_added += 1
        else:
            # Already on file, but the position may have been re-shaped around
            # it (a split collapsing back to one row).
            db.execute("UPDATE trade_fills SET trade_id=?, position_key=? WHERE fill_key=?",
                       (primary, pkey, fill["fill_key"]))

    return created, updated, fills_added, [action["ticker"]] * (created + updated)


def _company_fields(ticker, fallback_name):
    """Name/sector/industry from the local cache only — an import shouldn't
    stall on a round of SEC lookups. Whatever's missing fills in the first time
    the row is opened in the trade form."""
    from routes.company import _read_cache, _smart_title_case
    cached = _read_cache(ticker) or {}
    name = cached.get("company_name") or _smart_title_case(fallback_name) or fallback_name or ""
    return name, cached.get("sector") or "", cached.get("industry") or ""


def _insert_trade(db, d, strategy, pkey, now):
    pl, roi, days, win_loss = _compute_pl(
        d["entry_price"], d["shares"], d.get("exit_price"),
        d["entry_date"], d.get("exit_date"), d.get("entry_fee"), d.get("exit_fee"))
    name, sector, industry = _company_fields(d["ticker"], d.get("company_name"))
    pos = None
    if not d.get("exit_date"):
        pos = _portfolio_pos_pct(d["entry_price"], d["shares"], d["currency"],
                                 d.get("entry_fee"))
    cur = db.execute("""
        INSERT INTO trades (
            ticker, company_name, sector, industry, strategy, currency,
            entry_date, entry_price, shares, position_size_pct,
            exit_date, exit_price, entry_fee, exit_fee,
            pl_dollar, roi_pct, days_held, win_loss,
            notes, import_key, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        d["ticker"], name, sector, industry, strategy, d["currency"],
        d["entry_date"], d["entry_price"], d["shares"], pos,
        d.get("exit_date"), d.get("exit_price"), d.get("entry_fee"), d.get("exit_fee"),
        pl, roi, days, win_loss, "", pkey, now, now,
    ))
    return cur.lastrowid


def _update_trade(db, tid, d, pkey, now):
    """Overwrite only the derived columns — notes and strategy stay put."""
    pl, roi, days, win_loss = _compute_pl(
        d["entry_price"], d["shares"], d.get("exit_price"),
        d["entry_date"], d.get("exit_date"), d.get("entry_fee"), d.get("exit_fee"))
    pos_clause, pos_args = "", ()
    if not d.get("exit_date"):
        pos = _portfolio_pos_pct(d["entry_price"], d["shares"], d["currency"],
                                 d.get("entry_fee"))
        if pos is not None:
            pos_clause, pos_args = "position_size_pct=?, ", (pos,)
    sets = ", ".join(f"{c}=?" for c in _DERIVED_COLUMNS)
    db.execute(
        f"UPDATE trades SET {sets}, currency=?, {pos_clause}"
        "pl_dollar=?, roi_pct=?, days_held=?, win_loss=?, import_key=?, updated_at=? "
        "WHERE id=?",
        tuple(d.get(c) for c in _DERIVED_COLUMNS) + (d["currency"],) + pos_args
        + (pl, roi, days, win_loss, pkey, now, tid),
    )


@bp.route("/history", methods=["GET"])
def history():
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM trade_imports ORDER BY id DESC LIMIT 20").fetchall()
    return jsonify({"success": True, "data": [dict(r) for r in rows]})
