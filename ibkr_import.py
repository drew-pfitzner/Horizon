"""Import an IBKR transaction CSV into the trades log.

The shape problem
-----------------
Horizon's `trades` table is one row per *position*: a single entry price, a
single share count, one optional exit. IBKR's CSV is one row per *fill* — a
$100 order of DECK comes back as two lines at slightly different prices, and a
position you scale into over three weeks is six lines spread across the file.

So the import can't map rows to rows. It keeps a **fills ledger**
(`trade_fills`) underneath the position log: every fill the importer has ever
seen, fingerprinted, linked to the trade row it belongs to. A position row is
then *derived* from its fills — weighted-average entry, summed commission,
weighted-average exit — and re-derived from scratch every time new fills land.

That buys three things Drew asked for:

* **Idempotence.** A fill already in the ledger is recognised by fingerprint
  and contributes nothing new, so re-pasting last month's file is a no-op. Paste
  a 1-month file, then an all-time file, and only the fills you've never seen
  move the numbers.
* **Order independence.** Derivation is sums and weighted averages over the
  *union* of ledger + file, so importing an older window after a newer one lands
  on the same answer as doing it the other way round.
* **Scale-ins and sell-outs.** Adding to a live position is just more buy fills
  (the row's entry price becomes the weighted average); selling out is sell
  fills that flatten the position and close the row.

Rows logged by hand, before any of this existed, are folded in by synthesising a
*baseline* fill from the row itself (see `_baseline_fills`) — so a hand-entered
open position can be closed by a CSV that only contains the sell.

Nothing in this module touches the database. It parses, it plans, and it hands
the plan back for a human to look at; `routes/trade_import.py` does the writing.
"""

import csv
import io
import re
from collections import defaultdict
from datetime import date, datetime

# Share quantities are fractional and arrive as float text, so "flat" has to be
# a tolerance rather than == 0.
QTY_EPS = 1e-6

BUY, SELL = "BUY", "SELL"

_BUY_WORDS = {"BUY", "BOT", "B", "BUYTOOPEN", "BUYTOCOVER", "PURCHASE"}
_SELL_WORDS = {"SELL", "SLD", "S", "SELLTOCLOSE", "SELLSHORT", "SALE"}

# A forex leg is a trade in IBKR's eyes but not a position in Horizon's.
_FX_SYMBOL = re.compile(r"^[A-Z]{3}[./][A-Z]{3}$")

_EMPTY = {"", "-", "--", "n/a", "na", "none"}


class ImportError_(ValueError):
    """Bad or unrecognisable CSV — carries a message meant for the user."""


# ---------------------------------------------------------------- parsing ---

def _norm_key(s):
    """Fold a CSV header into a comparable key: 'T. Price' -> 'tprice'."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# Candidate header names per field, most specific first.
_FIELD_ALIASES = {
    "date":       ["tradedate", "datetime", "date", "reportdate", "settledate"],
    "symbol":     ["symbol", "ticker", "underlyingsymbol"],
    "qty":        ["quantity", "qty", "shares"],
    "price":      ["tradeprice", "tprice", "price", "priceperunit"],
    "currency":   ["pricecurrency", "currencyprimary", "currency"],
    "commission": ["ibcommission", "commission", "commfee", "commissionandtax", "fee"],
    "side":       ["buysell", "transactiontype", "type", "activitycode"],
    "desc":       ["description", "securitydescription", "listingexchangedescription"],
    "txid":       ["transactionid", "tradeid", "ibexecid", "executionid"],
    "asset":      ["assetcategory", "assetclass"],
}


def _map_columns(header):
    """Map our field names onto this file's column indexes, by alias."""
    keys = [_norm_key(h) for h in header]
    out = {}
    for field, aliases in _FIELD_ALIASES.items():
        for alias in aliases:
            if alias in keys:
                out[field] = keys.index(alias)
                break
    return out


def _cell(row, idx):
    if idx is None or idx >= len(row):
        return ""
    return (row[idx] or "").strip()


def _num(raw):
    """Float from an IBKR cell. '-' means 'not applicable', not zero."""
    s = (raw or "").strip().replace(",", "")
    if s.lower() in _EMPTY:
        return None
    try:
        return float(s)
    except ValueError:
        return None


_DATE_PATTERNS = ["%Y-%m-%d", "%Y%m%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d",
                  "%B %d, %Y", "%b %d, %Y"]


def _parse_date(raw):
    """ISO date from the several shapes IBKR uses. Time-of-day is dropped —
    Horizon logs trades by day.

    The whole string is tried before any trimming, because "August 14, 2026" and
    "2026-09-14, 09:30:00" both contain a comma and only one of them wants it
    cut off.
    """
    s = (raw or "").strip().strip('"')
    if not s or s.lower() in _EMPTY:
        return None
    candidates = [s]
    # "2026-09-14, 09:30:00" / "20260914;093000" / "2026-09-14 09:30"
    for sep in (",", ";", " "):
        if sep in s:
            candidates.append(s.split(sep)[0].strip())
    for candidate in candidates:
        for fmt in _DATE_PATTERNS:
            try:
                return datetime.strptime(candidate, fmt).date().isoformat()
            except ValueError:
                continue
    return None


def _split_sections(rows):
    """IBKR's statement CSVs interleave sections, each with its own header row:

        Transaction History,Header,Date,Account,Description,...
        Transaction History,Data,2026-09-14,U***56746,DECKERS OUTDOOR CORP,...

    Return {section: [(header, [data rows]), ...]} — a *list* of blocks per
    section, because one section can change columns mid-stream. An Activity
    Statement's Trades section emits a Stocks block (with 'Comm/Fee') and then a
    Forex block (with 'Comm in AUD'); folding them onto one header silently
    mis-reads the commission of every stock fill. A flat CSV (a Flex query
    export) has no section prefix and comes back as one block under the key ''.

    Rows flagged anything other than Header/Data — IBKR's SubTotal and Total
    lines — are dropped here: they restate fills that are already in the file.
    """
    sectioned = defaultdict(list)
    flat_header, flat_rows = None, []
    looks_sectioned = any(len(r) >= 2 and r[1].strip() in ("Header", "Data") for r in rows)

    for row in rows:
        if not row or not any(c.strip() for c in row):
            continue
        if looks_sectioned and len(row) >= 2 and row[1].strip() in ("Header", "Data"):
            section = row[0].strip()
            if row[1].strip() == "Header":
                sectioned[section].append((row[2:], []))
            elif sectioned[section]:
                sectioned[section][-1][1].append(row[2:])
            continue
        if not looks_sectioned:
            if flat_header is None:
                flat_header = row
            else:
                flat_rows.append(row)

    out = {s: blocks for s, blocks in sectioned.items() if blocks}
    if flat_header is not None:
        out[""] = [(flat_header, flat_rows)]
    return out


def _side_of(side_raw, qty):
    """BUY/SELL from the type column, falling back to the sign of the quantity.
    Anything else (Dividend, Forex Trade Component, Adjustment) is not a trade."""
    token = re.sub(r"[^A-Z]", "", (side_raw or "").upper())
    if token in _BUY_WORDS:
        return BUY
    if token in _SELL_WORDS:
        return SELL
    if side_raw is None or side_raw.strip() in _EMPTY:
        if qty is None:
            return None
        return BUY if qty > 0 else SELL
    return None


def _section_rows(sections, name):
    """Every data row of a section, across all of its header blocks."""
    out = []
    for _header, rows in sections.get(name, []):
        out.extend(rows)
    return out


def _field(sections, name, *labels):
    """Value of a 'Field Name,Field Value' row, e.g. Base Currency -> 'AUD'."""
    wanted = {l.lower() for l in labels}
    for row in _section_rows(sections, name):
        if len(row) >= 2 and row[0].strip().lower() in wanted:
            return row[1].strip().strip('"')
    return None


def _period_from_statement(sections):
    """'August 14, 2026 - September 14, 2026' off the Statement section."""
    for name in ("Statement", "Account Information"):
        raw = _field(sections, name, "period", "fromdate", "period covered")
        if not raw:
            continue
        parts = re.split(r"\s+-\s+|\s+to\s+", raw)
        start = _parse_date(parts[0])
        end = _parse_date(parts[-1]) if len(parts) > 1 else start
        if start:
            return start, end
    return None, None


def _account_from_statement(sections, fills):
    for f in fills:
        if f.get("account"):
            return f["account"]
    # An Activity Statement's Trades section carries no account column; the
    # number is stated once, up in Account Information.
    return _field(sections, "Account Information", "account", "account id")


def _portfolio_from_statement(sections, period_end):
    """What the account was worth at the end of the statement.

    The Net Asset Value section's Total row is the authority — 'Current Total',
    in the statement's base currency:

        Net Asset Value,Header,Asset Class,Prior Total,Current Long,Current Short,Current Total,Change
        Net Asset Value,Data,Total,6219.39982119,...,6216.276862505,-3.122958685

    Falls back to Change in NAV's Ending Value, which is the same figure stated
    a different way, for statements that omit the NAV breakdown. Returns None
    when the file carries neither — a Transaction History report or a Flex
    Query, typically, which say nothing about what the account is worth.
    """
    currency = (_field(sections, "Account Information", "base currency")
                or _field(sections, "Summary", "base currency") or "").upper() or None

    value = None
    for header, rows in sections.get("Net Asset Value", []):
        keys = [_norm_key(h) for h in header]
        if "currenttotal" not in keys:
            continue
        idx = keys.index("currenttotal")
        for row in rows:
            if row and row[0].strip().lower() == "total":
                value = _num(_cell(row, idx))
                break
        if value is not None:
            break

    if value is None:
        value = _num(_field(sections, "Change in NAV", "ending value") or "")
    if value is None:
        return None
    return {"value": value, "currency": currency, "as_of": period_end}


def parse_csv(text):
    """Parse an IBKR CSV into fills plus the context around them.

    Accepts the Transaction History report, an Activity Statement's Trades
    section, and a flat Flex Query export — they differ in layout but all carry
    the same handful of columns under different names.
    """
    if not (text or "").strip():
        raise ImportError_("Nothing pasted.")

    text = text.lstrip("﻿")
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error as e:
        raise ImportError_(f"Could not read that as CSV: {e}")

    sections = _split_sections(rows)
    if not sections:
        raise ImportError_("No CSV header row found.")

    fills = []
    ignored = defaultdict(int)
    dividends = []
    seen_fingerprints = defaultdict(int)
    account = None

    # Prefer the sections that actually hold trades; a statement can carry
    # several (Trades, Transaction History) describing the same executions, so
    # take the first that yields fills rather than double-counting them.
    preferred = ["Transaction History", "Trades", ""]
    ordered = [s for s in preferred if s in sections] + \
              [s for s in sections if s not in preferred]

    for section in ordered:
        section_fills = []
        # A section can change columns partway down (Stocks then Forex, in an
        # Activity Statement's Trades section), so each block brings its own
        # header and its own column map.
        for header, data_rows in sections[section]:
            cols = _map_columns(header)
            if not {"symbol", "qty", "price"} <= set(cols):
                continue

            keys = [_norm_key(h) for h in header]
            acct_idx = keys.index("account") if "account" in keys else None
            disc_idx = keys.index("datadiscriminator") if "datadiscriminator" in keys else None

            for row in data_rows:
                # Only `Order` rows are fills; SubTotal/Total restate them.
                if disc_idx is not None:
                    disc = _cell(row, disc_idx).lower()
                    if disc and disc not in ("order", "trade", "execution"):
                        continue

                symbol = _cell(row, cols.get("symbol")).upper()
                qty_raw = _num(_cell(row, cols.get("qty")))
                side_raw = _cell(row, cols.get("side")) if "side" in cols else None
                side = _side_of(side_raw, qty_raw)
                desc = _cell(row, cols.get("desc"))

                if side is None or symbol.lower() in _EMPTY or qty_raw is None:
                    label = (side_raw or "").strip() or "unrecognised row"
                    if label.lower() == "dividend" and symbol.lower() not in _EMPTY:
                        dividends.append({
                            "ticker": symbol,
                            "date": _parse_date(_cell(row, cols.get("date"))),
                            "description": desc,
                        })
                    ignored[label] += 1
                    continue

                asset = _cell(row, cols.get("asset")).upper() if "asset" in cols else ""
                if _FX_SYMBOL.match(symbol) or asset in ("CASH", "FOREX", "CFD"):
                    ignored["Forex / cash"] += 1
                    continue

                price = _num(_cell(row, cols.get("price")))
                trade_date = _parse_date(_cell(row, cols.get("date")))
                if price is None or trade_date is None:
                    ignored["Missing price or date"] += 1
                    continue

                qty = abs(qty_raw)
                if qty <= QTY_EPS:
                    ignored["Zero quantity"] += 1
                    continue

                commission = _num(_cell(row, cols.get("commission"))) if "commission" in cols else None
                commission = abs(commission) if commission is not None else None
                currency = (_cell(row, cols.get("currency")).upper() or "USD")
                if currency.lower() in _EMPTY:
                    currency = "USD"

                txid = _cell(row, cols.get("txid")) if "txid" in cols else ""
                acct = _cell(row, acct_idx) if acct_idx is not None else ""
                account = account or acct or None

                # Fingerprint. The broker's own id is best; otherwise the
                # economics of the fill, plus an occurrence counter so two
                # genuinely identical fills in one order stay distinct.
                if txid and txid.lower() not in _EMPTY:
                    fill_key = f"ibkr:tx:{txid}"
                else:
                    base = (f"ibkr:{symbol}|{trade_date}|{side}|"
                            f"{qty:.8f}|{price:.8f}")
                    seen_fingerprints[base] += 1
                    fill_key = f"{base}|{seen_fingerprints[base] - 1}"

                section_fills.append({
                    "fill_key": fill_key,
                    "ticker": symbol,
                    "trade_date": trade_date,
                    "side": side,
                    "qty": qty,
                    "price": price,
                    "commission": commission,
                    "currency": currency,
                    "description": desc,
                    "account": acct or None,
                    "source": "ibkr",
                    # Position order within the file, for replaying same-day
                    # fills in the order the broker listed them.
                    "row": len(section_fills),
                })

        if section_fills:
            fills = section_fills
            break

    if not fills:
        raise ImportError_(
            "No Buy or Sell rows found. Expected an IBKR Transaction History "
            "report, an Activity Statement, or a Trades Flex Query export."
        )

    start, end = _period_from_statement(sections)
    dates = [f["trade_date"] for f in fills]
    if not start:
        start, end = min(dates), max(dates)
    if not end:
        end = max(dates)

    return {
        "fills": fills,
        "period": {"start": start, "end": end},
        "account": _account_from_statement(sections, fills) or account,
        "ignored": dict(ignored),
        "dividends": dividends,
        # An Activity Statement also says what the account is worth; a
        # Transaction History report doesn't, hence None rather than 0.
        "portfolio": _portfolio_from_statement(sections, end),
    }


# ------------------------------------------------------------- derivation ---

def _wavg(pairs):
    """Weighted average price. pairs = [(qty, price), ...]"""
    total_qty = sum(q for q, _ in pairs)
    if total_qty <= QTY_EPS:
        return None
    return sum(q * p for q, p in pairs) / total_qty


def _sum_commission(fills, commission_pct):
    """Total commission for one side. IBKR states it per fill; if a file omits
    the column we fall back to Horizon's configured rate, the same way the
    hand-entry form does."""
    total = 0.0
    for f in fills:
        if f.get("commission") is not None:
            total += abs(f["commission"])
        else:
            total += abs(f["qty"] * f["price"]) * commission_pct / 100
    return total


def _group_positions(fills):
    """Replay a single ticker's fills into successive positions.

    A position runs from the first buy until the share count returns to zero;
    the next buy after that starts a new one. Sells that arrive with nothing
    open (the file's window opened mid-position) collect into a group with no
    buys, which the planner surfaces as a question rather than guessing.
    """
    ordered = sorted(fills, key=lambda f: (f["trade_date"],
                                           0 if f["side"] == BUY else 1,
                                           f.get("row", 0), f["fill_key"]))
    groups, cur = [], None

    def _new():
        return {"buys": [], "sells": [], "qty": 0.0, "oversold": 0.0}

    for f in ordered:
        if cur is None:
            cur = _new()
        if f["side"] == BUY:
            # A buy arriving after the position went short-by-accounting means
            # the earlier sells belonged to shares bought before this window.
            cur["buys"].append(f)
            cur["qty"] += f["qty"]
        else:
            cur["sells"].append(f)
            cur["qty"] -= f["qty"]
        if cur["buys"] and abs(cur["qty"]) <= QTY_EPS:
            groups.append(cur)
            cur = None
        elif cur["qty"] < -QTY_EPS and cur["buys"]:
            # Sold more than this file shows being bought.
            cur["oversold"] = -cur["qty"]
    if cur is not None:
        groups.append(cur)
    return groups


def derive_rows(group, commission_pct, split_partial=True):
    """Turn one position group into the 1–2 trade rows that represent it.

    Flat position   -> one closed row.
    Untouched entry -> one open row.
    Partly sold     -> a closed row for the shares that left plus an open row
                       for what's still held (`split_partial`), with the entry
                       commission apportioned between them. The alternative is
                       a single open row at the reduced size, which is tidier
                       but throws away the realised P/L.
    """
    buys, sells = group["buys"], group["sells"]
    if not buys:
        return []

    bought = sum(f["qty"] for f in buys)
    sold = sum(f["qty"] for f in sells)
    open_qty = bought - sold

    avg_entry = _wavg([(f["qty"], f["price"]) for f in buys])
    entry_fee = _sum_commission(buys, commission_pct)
    entry_date = min(f["trade_date"] for f in buys)
    currency = buys[0]["currency"]
    description = next((f["description"] for f in buys if f["description"]), "")

    base = {
        "ticker": buys[0]["ticker"],
        "currency": currency,
        "entry_date": entry_date,
        "entry_price": avg_entry,
        "description": description,
    }

    if sold <= QTY_EPS:                       # never sold: one open row
        return [dict(base, slot="open", shares=bought, entry_fee=entry_fee,
                     exit_date=None, exit_price=None, exit_fee=None)]

    avg_exit = _wavg([(f["qty"], f["price"]) for f in sells])
    exit_fee = _sum_commission(sells, commission_pct)
    exit_date = max(f["trade_date"] for f in sells)

    if open_qty <= QTY_EPS:                   # flat: one closed row
        return [dict(base, slot="closed", shares=bought, entry_fee=entry_fee,
                     exit_date=exit_date, exit_price=avg_exit, exit_fee=exit_fee)]

    if not split_partial:                     # keep it as one shrunken position
        return [dict(base, slot="open", shares=open_qty,
                     entry_fee=entry_fee * open_qty / bought,
                     exit_date=None, exit_price=None, exit_fee=None)]

    return [
        dict(base, slot="closed", shares=sold,
             entry_fee=entry_fee * sold / bought,
             exit_date=exit_date, exit_price=avg_exit, exit_fee=exit_fee),
        dict(base, slot="open", shares=open_qty,
             entry_fee=entry_fee * open_qty / bought,
             exit_date=None, exit_price=None, exit_fee=None),
    ]


# ---------------------------------------------------------------- baseline ---

def _baseline_fills(trade):
    """Synthesise the fills a hand-logged trade row implies.

    Without this, a CSV holding only the *sell* of a position you typed in by
    hand would look like a sale out of nowhere. With it, the row joins the
    ledger as its own opening buy (and closing sell, if it's already closed)
    and the file's fills merge into the same position.
    """
    if not trade.get("shares") or trade.get("entry_price") is None:
        return []
    tid = trade["id"]
    out = [{
        "fill_key": f"manual:{tid}:entry",
        "ticker": trade["ticker"],
        "trade_date": trade.get("entry_date") or "",
        "side": BUY,
        "qty": float(trade["shares"]),
        "price": float(trade["entry_price"]),
        "commission": float(trade["entry_fee"]) if trade.get("entry_fee") is not None else None,
        "currency": (trade.get("currency") or "USD").upper(),
        "description": trade.get("company_name") or "",
        "source": "manual",
        "trade_id": tid,
        "row": -2,
    }]
    if trade.get("exit_date") and trade.get("exit_price") is not None:
        out.append({
            "fill_key": f"manual:{tid}:exit",
            "ticker": trade["ticker"],
            "trade_date": trade["exit_date"],
            "side": SELL,
            "qty": float(trade["shares"]),
            "price": float(trade["exit_price"]),
            "commission": float(trade["exit_fee"]) if trade.get("exit_fee") is not None else None,
            "currency": (trade.get("currency") or "USD").upper(),
            "description": trade.get("company_name") or "",
            "source": "manual",
            "trade_id": tid,
            "row": -1,
        })
    return out


def _qty_close(a, b):
    return abs(a - b) <= max(1e-6, abs(b) * 1e-4)


def _superseding_fills(baseline, file_fills):
    """The file's fills that a baseline is merely a hand-typed summary of.

    A row entered in the evening after the trade describes the same shares the
    CSV will describe next month. Folding in both would double the position, so
    when the file shows the same quantity on the same date the real fills win.
    Returns them (so the row can be adopted rather than duplicated), or [].
    """
    same_day = [f for f in file_fills
                if f["side"] == baseline["side"] and f["trade_date"] == baseline["trade_date"]]
    if not same_day:
        return []
    if not _qty_close(sum(f["qty"] for f in same_day), baseline["qty"]):
        return []
    return same_day


# ----------------------------------------------------------------- planner ---

_COMPARE_FIELDS = [
    ("entry_date", None), ("entry_price", 6), ("shares", 8), ("entry_fee", 6),
    ("exit_date", None), ("exit_price", 6), ("exit_fee", 6),
]


def _rounded(value, digits):
    if value is None:
        return None
    if digits is None:
        return value
    return round(float(value), digits)


def _diff(current, derived):
    """Field-by-field difference between the stored row and the derived one."""
    out = {}
    for field, digits in _COMPARE_FIELDS:
        was = _rounded(current.get(field) if current else None, digits)
        now = _rounded(derived.get(field), digits)
        if was in ("", None) and now in ("", None):
            continue
        if was != now:
            out[field] = {"was": was, "now": now}
    return out


def build_plan(parsed, existing_trades, known_fill_keys, commission_pct=1.0,
               resolutions=None):
    """Work out what this file would change, without changing anything.

    `existing_trades` is every row of `trades` (dicts) with a `fill_count`;
    `known_fill_keys` is every fingerprint already in the ledger. `resolutions`
    maps an action key to the choice a human made about it last time round, so
    the same plan can be rebuilt on apply with the questions answered.
    """
    resolutions = resolutions or {}
    file_fills = parsed["fills"]
    period = parsed["period"]

    by_ticker = defaultdict(list)
    for f in file_fills:
        by_ticker[f["ticker"]].append(f)

    trades_by_ticker = defaultdict(list)
    trade_index = {}
    by_import_key = defaultdict(list)
    for t in existing_trades:
        trades_by_ticker[(t.get("ticker") or "").upper()].append(t)
        trade_index[t["id"]] = t
        if t.get("import_key"):
            by_import_key[t["import_key"]].append(t)

    # Fills already in the ledger, so a group can be rebuilt from the union.
    ledger_by_ticker = defaultdict(list)
    for f in parsed.get("ledger_fills", []):
        ledger_by_ticker[f["ticker"]].append(f)

    actions = []
    for ticker in sorted(by_ticker):
        new_fills = [f for f in by_ticker[ticker] if f["fill_key"] not in known_fill_keys]
        ledger = ledger_by_ticker.get(ticker, [])
        ledger_keys = {f["fill_key"] for f in ledger}

        # Union: what's already recorded, plus what this file adds.
        union = list(ledger) + [f for f in by_ticker[ticker] if f["fill_key"] not in ledger_keys]

        # Hand-logged rows that have no fills of their own join as baselines,
        # unless the file plainly contains the very fills they stand for.
        for t in trades_by_ticker.get(ticker, []):
            # A row with fills, or one the importer created, is already spoken
            # for. The second test matters for the open half of a split: its
            # fills hang off the *other* half, so it looks fill-less while being
            # fully accounted for, and a baseline would double the position.
            if t.get("fill_count") or t.get("import_key"):
                continue
            for b in _baseline_fills(t):
                superseding = _superseding_fills(b, by_ticker[ticker])
                if superseding:
                    # The file describes the very fills this row was typed from.
                    # Drop the baseline so the position isn't doubled, but mark
                    # the fills as belonging to the row — otherwise the position
                    # would look brand new and get logged a second time.
                    for f in superseding:
                        f.setdefault("adopt_trade_id", t["id"])
                    continue
                union.append(b)

        if not new_fills:
            # Everything here is already recorded — nothing to do for this ticker.
            actions.append({
                "key": f"{ticker}:settled",
                "ticker": ticker,
                "action": "skip",
                "reason": "Already imported — every fill in this file is already logged.",
                "new_fill_count": 0,
                "fills": [],
            })
            continue

        for idx, group in enumerate(_group_positions(union)):
            group_new = [f for f in (group["buys"] + group["sells"])
                         if f["fill_key"] not in known_fill_keys and f["source"] == "ibkr"]
            if not group_new:
                continue  # this position predates the file's new rows

            key = f"{ticker}:{idx}"
            choice = resolutions.get(key) or {}
            actions.append(_plan_group(ticker, key, group, group_new, choice,
                                       commission_pct, period, trade_index,
                                       by_import_key))

    # A skip row per ticker is noise when something else on that ticker moved.
    moved = {a["ticker"] for a in actions if a["action"] != "skip"}
    actions = [a for a in actions if a["action"] != "skip" or a["ticker"] not in moved]

    return {
        "period": period,
        "account": parsed.get("account"),
        "portfolio": parsed.get("portfolio"),
        "fills_in_file": len(file_fills),
        "fills_new": len([f for f in file_fills if f["fill_key"] not in known_fill_keys]),
        "fills_known": len([f for f in file_fills if f["fill_key"] in known_fill_keys]),
        "ignored": parsed.get("ignored", {}),
        "notices": _notices(parsed, existing_trades),
        "actions": actions,
        "needs_input": [a["key"] for a in actions if a["action"] == "ambiguous"],
    }


def position_key(ticker, group):
    """Stable name for a position: the ticker plus the date it was opened.

    Written onto both the trade rows and their fills, so a position that became
    *two* rows (a partial sale split into a closed and an open half) can still be
    found as one thing next time a CSV lands.
    """
    if group["buys"]:
        return f"{ticker}|{min(f['trade_date'] for f in group['buys'])}"
    return f"{ticker}|sell|{min(f['trade_date'] for f in group['sells'])}"


def _plan_group(ticker, key, group, group_new, choice, commission_pct, period,
                trade_index, by_import_key):
    """Decide what one position group means for the trade log."""
    pkey = position_key(ticker, group)

    # Rows this position already owns: whatever its fills point at, plus
    # anything still carrying the position key (the split's other half, whose
    # fills all hang off the primary row).
    linked = []
    for f in group["buys"] + group["sells"]:
        for tid in (f.get("trade_id"), f.get("adopt_trade_id")):
            if tid is not None and tid not in linked:
                linked.append(tid)
    for t in by_import_key.get(pkey, []):
        if t["id"] not in linked:
            linked.append(t["id"])

    fills_view = [{
        "date": f["trade_date"], "side": f["side"], "qty": f["qty"],
        "price": f["price"], "commission": f.get("commission"),
        "known": f["fill_key"] not in {n["fill_key"] for n in group_new},
        "source": f["source"],
    } for f in sorted(group["buys"] + group["sells"],
                      key=lambda f: (f["trade_date"], 0 if f["side"] == BUY else 1))]

    base = {
        "key": key,
        "ticker": ticker,
        "position_key": pkey,
        "new_fill_count": len(group_new),
        "fills": fills_view,
        "trade_ids": linked,
        # Raw fills for the writer. Stripped before the plan goes over the wire
        # (see strip_internals) — apply rebuilds the plan server-side rather
        # than trusting numbers that made a round trip through the browser.
        "_fills": group["buys"] + group["sells"],
    }

    # --- a sale with no position behind it -------------------------------
    if not group["buys"]:
        sold = sum(f["qty"] for f in group["sells"])
        first_sell = min(f["trade_date"] for f in group["sells"])
        if choice.get("mode") == "entry" and choice.get("entry_price"):
            synthetic = {
                "fill_key": f"resolved:{key}:entry",
                "ticker": ticker, "side": BUY, "qty": sold,
                "price": float(choice["entry_price"]),
                "trade_date": choice.get("entry_date") or first_sell,
                "commission": None,
                "currency": group["sells"][0]["currency"],
                "description": group["sells"][0]["description"],
                "source": "resolved", "row": -3,
            }
            filled = {"buys": [synthetic], "sells": group["sells"], "qty": 0.0}
            rows = derive_rows(filled, commission_pct)
            return dict(base, action="create", reason="Entry supplied by you.",
                        targets=[{"slot": r["slot"], "trade_id": None,
                                  "derived": _public(r), "diff": _diff(None, r)}
                                 for r in rows],
                        _fills=[synthetic] + group["sells"])
        if choice.get("mode") == "ignore":
            return dict(base, action="skip",
                        reason="You chose to leave this sale out of the log.")
        return dict(
            base, action="ambiguous", question="orphan_sell",
            reason=(f"{ticker}: {_fmt_qty(sold)} shares sold on {first_sell}, but this "
                    f"file has no matching buy and there's no open {ticker} position "
                    f"in Horizon. The shares were bought before "
                    f"{period.get('start') or 'this window'}."),
            options=[
                {"mode": "entry", "label": "Enter what you paid",
                 "detail": "Give the entry date and average price; the round trip gets logged in full.",
                 "needs": ["entry_date", "entry_price"], "recommended": True},
                {"mode": "ignore", "label": "Leave it out",
                 "detail": "No row is created. Re-run with a wider CSV and the buy will fill itself in."},
            ],
            suggestion={"entry_date": None, "entry_price": None},
        )

    # --- more sold than this window bought -------------------------------
    if group.get("oversold", 0) > QTY_EPS and choice.get("mode") != "as_is":
        return dict(
            base, action="ambiguous", question="oversold",
            reason=(f"{ticker}: the sells here exceed the buys by "
                    f"{_fmt_qty(group['oversold'])} shares, so part of the position "
                    f"was opened before this file starts."),
            options=[
                {"mode": "as_is", "label": "Log what's in the file",
                 "detail": "Records the buys and sells present; the missing shares are ignored.",
                 "recommended": True},
                {"mode": "ignore", "label": "Skip this position",
                 "detail": "Leave it alone and import a longer CSV instead."},
            ],
        )
    if choice.get("mode") == "ignore":
        return dict(base, action="skip", reason="Skipped at your request.")

    # --- a partial sale needs a shape ------------------------------------
    bought = sum(f["qty"] for f in group["buys"])
    sold = sum(f["qty"] for f in group["sells"])
    partial = sold > QTY_EPS and (bought - sold) > QTY_EPS
    split = choice.get("mode") != "reduce"

    rows = derive_rows(group, commission_pct, split_partial=split)
    if not rows:
        return dict(base, action="skip", reason="Nothing to record.")

    # --- line the derived rows up with the rows already in the log -------
    targets, used = [], set()
    for r in rows:
        match = _match_row(r, linked, used, trade_index)
        if match is not None:
            used.add(match["id"])
        targets.append({
            "slot": r["slot"],
            "trade_id": match["id"] if match else None,
            "derived": _public(r),
            "diff": _diff(match, r),
        })

    orphaned = [tid for tid in linked if tid not in used]
    changed = any(t["diff"] or t["trade_id"] is None for t in targets)

    action = "create" if all(t["trade_id"] is None for t in targets) else (
        "update" if changed else "skip")
    reason = _reason_for(action, ticker, group, partial, split, orphaned)

    out = dict(base, action=action, reason=reason, targets=targets,
               orphaned_trade_ids=orphaned)
    if partial:
        out["question"] = "partial_exit"
        out["options"] = [
            {"mode": "split", "label": "Split it",
             "detail": "A closed row for the shares sold (keeping the realised P/L) "
                       "plus an open row for what you still hold.",
             "recommended": True, "selected": split},
            {"mode": "reduce", "label": "Just shrink the position",
             "detail": "One open row at the smaller size. The realised P/L isn't logged.",
             "selected": not split},
        ]
    return out


def _match_row(derived, linked_ids, used, trade_index):
    """Which existing trade row, if any, this derived row should overwrite.

    Prefer a row whose open/closed state already matches the derived one — that
    keeps a split's open half on the row that was open — then fall back to any
    unused linked row.
    """
    for tid in linked_ids:
        row = trade_index.get(tid)
        if tid in used or row is None:
            continue
        if (derived["slot"] == "open") == (not row.get("exit_date")):
            return row
    for tid in linked_ids:
        row = trade_index.get(tid)
        if tid not in used and row is not None:
            return row
    return None


def _reason_for(action, ticker, group, partial, split, orphaned):
    n_buy = len(group["buys"])
    n_sell = len(group["sells"])
    if action == "create":
        if n_sell:
            return f"New round trip: {n_buy} buy fill(s), {n_sell} sell fill(s)."
        return f"New position from {n_buy} buy fill(s)."
    if action == "skip":
        return "Already matches what's logged."
    bits = []
    if n_sell and not partial:
        bits.append("closes the position")
    elif partial:
        bits.append("partly sold" + (" — splitting into a closed and an open row" if split else ""))
    if n_buy > 1:
        bits.append("entry re-averaged across the added fills")
    if orphaned:
        bits.append(f"{len(orphaned)} existing row(s) folded in")
    return f"Updates the logged {ticker} position: " + ", ".join(bits or ["figures refreshed"]) + "."


def _public(row):
    """The derived row as the UI and the writer both want it."""
    return {
        "ticker": row["ticker"],
        "currency": row["currency"],
        "entry_date": row["entry_date"],
        "entry_price": _rounded(row["entry_price"], 6),
        "shares": _rounded(row["shares"], 8),
        "entry_fee": _rounded(row["entry_fee"], 6),
        "exit_date": row.get("exit_date"),
        "exit_price": _rounded(row.get("exit_price"), 6),
        "exit_fee": _rounded(row.get("exit_fee"), 6),
        "company_name": _clean_name(row.get("description")),
    }


def _clean_name(desc):
    """IBKR descriptions are shouty and occasionally carry the class suffix."""
    if not desc:
        return ""
    return re.sub(r"\s+", " ", desc).strip()


def _fmt_qty(q):
    return f"{q:.4f}".rstrip("0").rstrip(".")


def strip_internals(plan):
    """A JSON-safe copy of the plan: the raw fill objects the writer needs are
    of no use to the browser and shouldn't be trusted coming back from it."""
    return dict(plan, actions=[{k: v for k, v in a.items() if not k.startswith("_")}
                               for a in plan["actions"]])


def _notices(parsed, existing_trades):
    """Context worth showing but not acting on."""
    out = []
    held = {(t.get("ticker") or "").upper() for t in existing_trades if not t.get("exit_date")}
    traded = {f["ticker"] for f in parsed["fills"]}
    for d in parsed.get("dividends", []):
        where = "" if d["ticker"] in held or d["ticker"] in traded else \
                " — no position on file, so you may be holding it outside Horizon"
        out.append(f"{d['ticker']}: dividend on {d['date'] or 'an unknown date'}{where}. "
                   f"Dividends aren't part of the trade log.")
    return out
