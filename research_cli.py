#!/usr/bin/env python3
"""
Horizon research CLI — automated ticker research from SEC EDGAR.

Pulls XBRL company facts from SEC EDGAR and reproduces the Research view's
Fundamentals checklist + Freedom Trader equity-multiple valuation, so you can
sanity-check a ticker in the terminal before touching finviz / TradingView.

Usage:
    python3 research_cli.py GOOG
    python3 research_cli.py GOOG AAPL MSFT
    python3 research_cli.py GOOG --price 319.45      # override live price
    python3 research_cli.py GOOG --required 12       # required return %
    python3 research_cli.py GOOG --json              # machine-readable output

Notes:
  * Negative-equity companies are VETOED — the equity-multiple model divides by
    book equity and produces garbage when equity < 0.
  * "EPS Growth Next Yr" and "Top 3 SM Increasing" need analyst estimates / QoQ
    smart-money deltas and are reported as MANUAL (check finviz yourself).
  * Live price comes from Stooq (free, no key). Use --price if it can't resolve.
"""

import argparse
import http.cookiejar
import json
import sqlite3
import statistics
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# Share DB/cache paths with the Horizon app (honours env vars in Docker/dev);
# fall back to repo-relative paths when run as a bare standalone script.
try:
    from config import SMART_MONEY_DB as SM_DB, BASE_DIR
except Exception:
    BASE_DIR = Path(__file__).parent
    SM_DB = BASE_DIR / "data" / "smart_money.db"
CACHE_DIR = BASE_DIR / "data" / "cache"
TICKERS_CACHE = CACHE_DIR / "sec_company_tickers.json"
TICKERS_TTL = 7 * 24 * 3600

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=1d"
YAHOO_QS_URL = ("https://query2.finance.yahoo.com/v10/finance/quoteSummary/"
                "{sym}?modules=earningsTrend,defaultKeyStatistics&crumb={crumb}")
YAHOO_CRUMB_URL = "https://query2.finance.yahoo.com/v1/test/getcrumb"
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
STOOQ_URL = "https://stooq.com/q/l/?s={sym}.us&f=sd2t2ohlcv&h&e=csv"

# Identify yourself to SEC (they ask for a contact). Falls back if not set.
USER_AGENT = "Horizon research CLI drew.pfitzner@gmail.com"

# Above this median ROE the equity-multiple model is unreliable: it usually means
# buybacks have shrunk book equity to a sliver, inflating ROE and exploding the
# multiplier into a nonsense valuation (see AAPL/HD). Treat like negative equity.
ROE_SANITY_CAP = 50.0

# ANSI colours
G, R, Y, B, DIM, RST = "\033[92m", "\033[91m", "\033[93m", "\033[94m", "\033[2m", "\033[0m"


# ─────────────────────────── HTTP helpers ───────────────────────────

def _get_json(url, timeout=30):
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_text(url, timeout=15):
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def fetch_sic(cik):
    """(sic_code, description) from SEC submissions. Used to skip financials —
    the equity-multiple model needs a different (bank) valuation method."""
    try:
        sub = _get_json(SEC_SUBMISSIONS_URL.format(cik=cik))
        return str(sub.get("sic") or ""), (sub.get("sicDescription") or "")
    except (URLError, HTTPError, TimeoutError, ValueError, KeyError):
        return "", ""


def is_financial(sic):
    """SIC 6000–6799 = Finance / Insurance / Real Estate (banks, insurers,
    brokers, REITs, holding cos). Equity-multiple valuation doesn't apply."""
    try:
        return 6000 <= int(sic) <= 6799
    except (TypeError, ValueError):
        return False


def resolve_cik(ticker):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fresh = TICKERS_CACHE.exists() and (time.time() - TICKERS_CACHE.stat().st_mtime) < TICKERS_TTL
    if not fresh:
        try:
            TICKERS_CACHE.write_text(json.dumps(_get_json(SEC_TICKERS_URL)))
        except (URLError, HTTPError, TimeoutError, json.JSONDecodeError):
            if not TICKERS_CACHE.exists():
                return None, None
    raw = json.loads(TICKERS_CACHE.read_text())
    for _, row in raw.items():
        if str(row.get("ticker", "")).upper() == ticker:
            return str(row.get("cik_str", "")).zfill(10), row.get("title")
    return None, None


def fetch_price(ticker, override):
    if override is not None:
        return override, "manual"
    # Primary: Yahoo chart API (free, no key)
    try:
        data = _get_json(YAHOO_URL.format(sym=ticker), timeout=15)
        meta = data["chart"]["result"][0]["meta"]
        px = meta.get("regularMarketPrice") or meta.get("previousClose")
        if px:
            return float(px), "yahoo"
    except (URLError, HTTPError, TimeoutError, ValueError, KeyError, TypeError, IndexError):
        pass
    # Fallback: Stooq CSV
    try:
        csv = _get_text(STOOQ_URL.format(sym=ticker.lower()))
        lines = csv.strip().splitlines()
        if len(lines) >= 2:
            rec = dict(zip(lines[0].split(","), lines[1].split(",")))
            close = rec.get("Close")
            if close and close not in ("N/D", ""):
                return float(close), "stooq"
    except (URLError, HTTPError, TimeoutError, ValueError, KeyError):
        pass
    return None, None


# Yahoo's analyst-estimate (quoteSummary) endpoint needs a cookie + crumb. Build
# one authenticated opener per run and reuse it across tickers.
_YH = {"opener": None, "crumb": None}


def _yahoo_authed():
    if _YH["opener"] is None:
        cj = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        op.addheaders = [("User-Agent", BROWSER_UA)]
        try:  # seeds the consent/session cookie (returns an HTTPError we ignore)
            op.open("https://fc.yahoo.com/", timeout=15)
        except (URLError, HTTPError, TimeoutError):
            pass
        try:
            _YH["crumb"] = op.open(YAHOO_CRUMB_URL, timeout=15).read().decode().strip()
        except (URLError, HTTPError, TimeoutError):
            _YH["crumb"] = ""
        _YH["opener"] = op
    return _YH["opener"], _YH["crumb"]


def fetch_yahoo_extras(ticker):
    """One quoteSummary call → (total_shares, eps_next_growth_pct, source).

    total_shares uses impliedSharesOutstanding (all classes combined) so
    multi-class filers get the correct total; falls back to sharesOutstanding.
    eps_next_growth is the consensus 'next fiscal year' EPS growth % — a forward
    analyst estimate (not in SEC filings), undocumented + uneven coverage, so a
    hint not a hard gate.
    """
    try:
        op, crumb = _yahoo_authed()
        if not crumb:
            return None, None, None
        url = YAHOO_QS_URL.format(sym=urllib.parse.quote(ticker), crumb=urllib.parse.quote(crumb))
        res = json.loads(op.open(url, timeout=15).read())["quoteSummary"]["result"][0]
        ks = res.get("defaultKeyStatistics") or {}
        shares = (ks.get("impliedSharesOutstanding") or {}).get("raw") \
            or (ks.get("sharesOutstanding") or {}).get("raw")
        growth = None
        for t in (res.get("earningsTrend") or {}).get("trend", []):
            if t.get("period") == "+1y":
                growth = (t.get("growth") or {}).get("raw")
        return (float(shares) if shares else None,
                growth * 100.0 if growth is not None else None,
                "yahoo")
    except (URLError, HTTPError, TimeoutError, ValueError, KeyError, TypeError, IndexError):
        return None, None, None


# ─────────────────────── XBRL fact extraction ───────────────────────

def _series(gaap, tags, kind):
    """Return {fiscal_year: value} merged across the given tags.

    kind='flow'  -> income/cash-flow items (full-year duration, fp=FY)
    kind='stock' -> balance-sheet snapshots (instant, keyed by period-end year)
    Tags are tried in priority order; a year present in an earlier tag wins, but
    gaps are backfilled from later tags (companies sometimes switch XBRL tags
    mid-history, e.g. Revenues vs RevenueFromContractWithCustomer...).
    Within a tag, the most recently *filed* number for each year is kept.
    """
    out = {}
    for tag in tags:
        node = gaap.get(tag)
        if not node:
            continue
        units = node.get("units", {})
        if not units:
            continue
        unit_key = max(units, key=lambda u: len(units[u]))
        vals, filed = {}, {}
        for e in units[unit_key]:
            if e.get("fp") != "FY" or e.get("form") not in ("10-K", "10-K/A", "20-F"):
                continue
            end = e.get("end")
            if not end:
                continue
            if kind == "flow":
                start = e.get("start")
                if not start:
                    continue
                dur = (date.fromisoformat(end) - date.fromisoformat(start)).days
                if not (350 < dur < 380):
                    continue
            yr = int(end[:4])
            f = e.get("filed", "")
            if yr not in vals or f >= filed[yr]:  # latest-filed wins within a tag
                vals[yr] = e.get("val")
                filed[yr] = f
        for yr, v in vals.items():
            out.setdefault(yr, v)  # earlier tag wins across tags
    return out


def _latest(series, n=6):
    """Most-recent n years as list of (year, value), newest last."""
    return [(y, series[y]) for y in sorted(series)][-n:]


# ─────────────────────── valuation (mirror of routes/valuation.py) ───────────────────────

def valuation(roes, payouts, total_equity_m, shares_m, price, required=10.0):
    """roes: list of ROE % (any order). payouts: list of decimals. Newest-first not required."""
    if not roes or shares_m <= 0:
        return None
    eps_book = total_equity_m / shares_m

    roe_avg, roe_med = statistics.mean(roes), statistics.median(roes)
    roe_mos = roe_med * 0.90
    if payouts:
        pay_avg, pay_med = statistics.mean(payouts), statistics.median(payouts)
    else:
        pay_avg = pay_med = 0.0
    pay_mos = pay_med

    def mult(reinv, distrib):
        r, d = reinv / required, distrib / required
        return r * r + d * (1.0 + r)

    cols = {}
    for name, roe, pay in (("avg", roe_avg, pay_avg), ("median", roe_med, pay_med), ("mos", roe_mos, pay_mos)):
        distrib = roe * pay
        reinv = roe * (1.0 - pay)
        m = mult(reinv, distrib)
        v = eps_book * m
        disc = ((v - price) / v * 100) if v else 0.0
        cols[name] = {"valuation": v, "discount_pct": disc, "multiplier": m}

    if cols["mos"]["valuation"] > 0 and price <= cols["mos"]["valuation"]:
        assessment = "UNDERVALUED"
    elif cols["median"]["valuation"] > 0 and price <= cols["median"]["valuation"]:
        assessment = "FAIR_VALUE"
    else:
        assessment = "OVERVALUED"

    return {
        "eps_book": eps_book,
        "roe_median": roe_med, "roe_mos": roe_mos,
        "val_median": cols["median"]["valuation"], "val_mos": cols["mos"]["valuation"],
        "disc_median": cols["median"]["discount_pct"], "disc_mos": cols["mos"]["discount_pct"],
        "assessment": assessment,
    }


# ─────────────────────── smart money (local db) ───────────────────────

def smart_money(ticker):
    if not SM_DB.exists():
        return None
    try:
        db = sqlite3.connect(f"file:{SM_DB}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT h.portfolio_weight w, g.name FROM holdings h "
            "LEFT JOIN gurus g ON g.id = h.guru_id "
            "WHERE h.ticker = ? AND (h.put_call IS NULL OR h.put_call = '') "
            "AND h.report_period = (SELECT MAX(report_period) FROM holdings WHERE ticker = ?) "
            "ORDER BY h.portfolio_weight DESC",
            (ticker, ticker),
        ).fetchall()
        db.close()
        if not rows:
            return {"holders": 0, "max_weight": 0.0, "top": []}
        return {
            "holders": len(rows),
            "max_weight": rows[0]["w"] or 0.0,
            "top": [(r["name"] or "?", r["w"] or 0.0) for r in rows[:3]],
        }
    except sqlite3.Error:
        return None


# ─────────────────────── per-ticker analysis ───────────────────────

def analyze(ticker, price_override=None, required=10.0):
    cik, title = resolve_cik(ticker)
    if not cik:
        return {"ticker": ticker, "error": "ticker not found in SEC company index"}

    try:
        facts = _get_json(SEC_FACTS_URL.format(cik=cik))
    except HTTPError as e:
        if e.code == 404:
            # CIK resolved but SEC has no XBRL company facts — characteristic of
            # ETFs, mutual funds, and unit trusts, which don't file operating-
            # company financials. The equity-multiple model doesn't apply to them.
            fundish = any(w in (title or "").upper()
                          for w in ("ETF", "TRUST", "FUND", "INDEX"))
            what = "an ETF/fund" if fundish else "a fund or non-operating filer"
            return {"ticker": ticker,
                    "error": f"{ticker} ({title}) looks like {what} — SEC has no "
                             "company financials to prefill. This tool only works "
                             "for operating companies that file 10-Ks."}
        return {"ticker": ticker, "error": f"could not fetch SEC facts: {e}"}
    except (URLError, TimeoutError, json.JSONDecodeError) as e:
        return {"ticker": ticker, "error": f"could not fetch SEC facts: {e}"}

    sic, sic_desc = fetch_sic(cik)
    financial = is_financial(sic)

    gaap = facts.get("facts", {}).get("us-gaap", {})
    dei = facts.get("facts", {}).get("dei", {})
    if not gaap and "ifrs-full" in facts.get("facts", {}):
        return {"ticker": ticker,
                "error": "IFRS / foreign filer (20-F) — reports under ifrs-full, not us-gaap; not supported"}

    ni = _series(gaap, ["NetIncomeLoss", "ProfitLoss"], "flow")
    rev = _series(gaap, ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                         "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"], "flow")
    assets = _series(gaap, ["Assets"], "stock")
    equity = _series(gaap, ["StockholdersEquity",
                            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"], "stock")
    cur_assets = _series(gaap, ["AssetsCurrent"], "stock")
    cur_liab = _series(gaap, ["LiabilitiesCurrent"], "stock")
    eps = _series(gaap, ["EarningsPerShareDiluted", "EarningsPerShareBasic"], "flow")
    dil_shares = _series(gaap, ["WeightedAverageNumberOfDilutedSharesOutstanding",
                                "WeightedAverageNumberOfSharesOutstandingBasic"], "flow")
    # Some filers (e.g. VISA) report EPS only by share class, so companyfacts has
    # no undimensioned EPS. Synthesize from net income / diluted shares, or fall
    # back to net-income growth (same sign as EPS growth for the >0% test).
    eps_note = ""
    if len([y for y in eps if eps[y] is not None]) < 2:
        if dil_shares:
            eps = {y: ni[y] / dil_shares[y] for y in ni if dil_shares.get(y)}
            eps_note = " (NI/sh)"
        else:
            eps = dict(ni)
            eps_note = " (NI)"
    div_paid = _series(gaap, ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"], "flow")
    dps = _series(gaap, ["CommonStockDividendsPerShareDeclared", "CommonStockDividendsPerShareCashPaid"], "flow")
    ltd = _series(gaap, ["LongTermDebtNoncurrent", "LongTermDebt"], "stock")
    ltd_cur = _series(gaap, ["LongTermDebtCurrent"], "stock")
    st_debt = _series(gaap, ["ShortTermBorrowings", "DebtCurrent"], "stock")
    shares = _series(gaap, ["CommonStockSharesOutstanding", "WeightedAverageNumberOfDilutedSharesOutstanding",
                            "WeightedAverageNumberOfSharesOutstandingBasic"], "flow")
    shares_dei = _series(dei, ["EntityCommonStockSharesOutstanding"], "stock") if dei else {}

    if not ni or not equity:
        return {"ticker": ticker, "error": "insufficient fundamentals in SEC filings"}

    years = sorted(set(ni) & set(equity))[-5:]
    if not years:
        return {"ticker": ticker, "error": "no overlapping annual data"}
    latest = years[-1]

    def g(series, yr):
        return series.get(yr)

    # per-year derived ratios. ROE uses AVERAGE equity ((prior+current)/2) — the
    # standard method (and what the Horizon app / finviz use); falls back to
    # ending equity when the prior year isn't available.
    roe_by_year, payout_by_year = {}, {}
    for yr in years:
        e, n = g(equity, yr), g(ni, yr)
        pe = g(equity, yr - 1)
        base = (pe + e) / 2 if (pe and pe > 0 and e and e > 0) else e
        if base and base > 0 and n is not None:
            roe_by_year[yr] = n / base * 100.0
        # payout: prefer cash dividends / net income, else DPS/EPS. A year with no
        # dividend data is treated as 0% payout (non-payers before they initiated),
        # so the 5-yr median isn't skewed by only counting dividend years.
        pay = None
        if g(div_paid, yr) and n and n > 0:
            pay = g(div_paid, yr) / n
        elif g(dps, yr) and g(eps, yr) and g(eps, yr) > 0:
            pay = g(dps, yr) / g(eps, yr)
        payout_by_year[yr] = max(0.0, min(pay, 1.0)) if pay is not None else 0.0

    latest_equity = g(equity, latest)
    latest_ni = g(ni, latest)
    latest_assets = g(assets, latest)
    latest_rev = g(rev, latest)

    price, price_src = fetch_price(ticker, price_override)
    yahoo_shares, eps_next_growth, eps_next_src = fetch_yahoo_extras(ticker)

    # shares outstanding (absolute, ALL classes) for market cap + valuation.
    # Prefer Yahoo's implied total — companyfacts only exposes undimensioned
    # facts, so multi-class filers (VISA, GOOG…) have stale/partial SEC counts.
    sh = yahoo_shares
    sh_src = "yahoo" if sh else None
    if not sh:
        sh = (g(shares_dei, max(shares_dei)) if shares_dei else None) or g(shares, latest)
        sh_src = "sec" if sh else None

    # ── fundamentals checklist (latest FY) ──
    # flags is keyed by Horizon's DB field names so the app can prefill directly.
    checks = []
    flags = {}

    def chk(label, ok, detail, key=None):
        checks.append((label, ok, detail))
        if key:
            flags[key] = {"ok": bool(ok), "detail": detail}

    roe = roe_by_year.get(latest)
    roa = (latest_ni / latest_assets * 100.0) if latest_assets else None
    npm = (latest_ni / latest_rev * 100.0) if latest_rev else None
    total_debt = sum(v for v in (g(ltd, latest), g(ltd_cur, latest), g(st_debt, latest)) if v)
    de = (total_debt / latest_equity) if latest_equity and latest_equity > 0 else None
    roi = (latest_ni / (latest_equity + total_debt) * 100.0) if latest_equity and (latest_equity + total_debt) > 0 else None
    cr = (g(cur_assets, latest) / g(cur_liab, latest)) if g(cur_liab, latest) else None
    mcap = (price * sh / 1e9) if price and sh else None

    # growth: latest vs oldest available (within 5y window) and vs prior year
    eps_years = [y for y in sorted(eps) if y <= latest][-5:]
    eps_5 = (eps[eps_years[-1]] > eps[eps_years[0]]) if len(eps_years) >= 2 else None
    eps_1 = (eps[eps_years[-1]] > eps[eps_years[-2]]) if len(eps_years) >= 2 else None
    rev_years = [y for y in sorted(rev) if y <= latest][-5:]
    sales_5 = (rev[rev_years[-1]] > rev[rev_years[0]]) if len(rev_years) >= 2 else None

    chk("ROA > 8%", roa is not None and roa > 8, f"{roa:.1f}%" if roa is not None else "n/a", "f_roa")
    chk("ROE > 12%", roe is not None and roe > 12, f"{roe:.1f}%" if roe is not None else "n/a", "f_roe")
    chk("ROI > 8%", roi is not None and roi > 8, f"{roi:.1f}%" if roi is not None else "n/a", "f_roi")
    chk("Net Profit Margin > 0%", npm is not None and npm > 0, f"{npm:.1f}%" if npm is not None else "n/a", "f_npm")
    chk("EPS Growth Past 5 Yrs > 0%", eps_5, ("yes" if eps_5 else ("no" if eps_5 is not None else "n/a")) + eps_note, "f_eps_5yr")
    chk("EPS Growth Past Yr > 0%", eps_1, ("yes" if eps_1 else ("no" if eps_1 is not None else "n/a")) + eps_note, "f_eps_1yr")
    chk("Sales Growth Past 5 Yrs > 0%", sales_5, "yes" if sales_5 else ("no" if sales_5 is not None else "n/a"), "f_sales_5yr")
    chk("Current Ratio > 1", cr is not None and cr > 1, f"{cr:.2f}" if cr is not None else "n/a", "f_current_ratio")
    chk("Debt to Equity < 0.4", de is not None and de < 0.4, f"{de:.2f}" if de is not None else "n/a", "f_debt_equity")
    chk("Market Cap > $1B", mcap is not None and mcap > 1, f"${mcap:.1f}B" if mcap is not None else "n/a", "market_cap_ok")

    sm = smart_money(ticker)
    sm_ok = bool(sm and sm["max_weight"] > 2)
    sm_detail = f"{sm['max_weight']:.1f}% ({sm['holders']} gurus)" if sm else "no smart_money.db"
    chk("SM Holding > 2%", sm_ok, sm_detail, "sm_holding_5pct")

    fund_score = sum(1 for _, ok, _ in checks[:10] if ok)

    # ── valuation ──
    # Financials get no equity-multiple valuation — banks/insurers need a
    # dedicated method (TODO: user to define). Skip valuation + trade gate.
    val = None
    veto = latest_equity is not None and latest_equity <= 0
    veto_reason = "negative book equity" if veto else None
    if not veto and not financial:
        roes = [roe_by_year[y] for y in years if y in roe_by_year]
        payouts = [payout_by_year[y] for y in years if y in payout_by_year]
        if roes and sh and price:
            val = valuation(roes, payouts, latest_equity / 1e6, sh / 1e6, price, required)
            if val and val["roe_median"] > ROE_SANITY_CAP:
                veto = True
                veto_reason = f"buyback-distorted book equity (median ROE {val['roe_median']:.0f}%)"

    # a vetoed/unreliable valuation must NOT feed a false 'undervalued' signal
    price_below_mos = bool(not veto and val and price is not None
                           and val["val_mos"] > 0 and price <= val["val_mos"])

    # ── verdict (mirror of Critical Criteria) ──
    trade_ok = (roe is not None and roe > 12) and (npm is not None and npm > 0) and sm_ok
    invest_ok = trade_ok and price_below_mos
    if financial:
        verdict = f"SKIP — financial sector ({sic_desc or 'SIC ' + sic}); needs bank valuation method"
    elif veto:
        verdict = "VETOED — " + veto_reason
    elif invest_ok:
        verdict = "CAN INVEST"
    elif trade_ok:
        verdict = "CAN TRADE"
    else:
        verdict = "NO ACTION"

    return {
        "ticker": ticker, "company": title, "cik": cik, "latest_fy": latest, "years": years,
        "financial": financial, "sic": sic, "sic_desc": sic_desc,
        "price": price, "price_src": price_src,
        "checks": checks, "flags": flags, "fund_score": fund_score,
        "roe_by_year": roe_by_year, "payout_by_year": payout_by_year,
        "latest_equity_m": (latest_equity / 1e6) if latest_equity is not None else None,
        "shares_m": (sh / 1e6) if sh else None, "shares_src": sh_src,
        "required_return": required,
        "veto": veto, "veto_reason": veto_reason, "val": val, "price_below_mos": price_below_mos,
        "sm": sm, "verdict": verdict,
        "eps_next": {"growth": eps_next_growth, "src": eps_next_src},
        "manual": ["Top 3 SM Increasing Stake (QoQ)"],
    }


def to_horizon_prefill(a):
    """Map an analyze() result to the Horizon Research + Valuation form fields.

    - flags/details -> research checklist booleans (keyed by DB field name)
    - valuation -> roe1..5 / payout1..5 (latest first, payout as %), equity, shares
    Financials return checklist flags but no valuation (skipped upstream).
    """
    if a.get("error"):
        return {"ticker": a.get("ticker"), "error": a["error"]}

    flags = {k: v["ok"] for k, v in a.get("flags", {}).items()}
    details = {k: v["detail"] for k, v in a.get("flags", {}).items()}

    en = a.get("eps_next") or {}
    if en.get("growth") is not None:
        flags["f_eps_next"] = en["growth"] > 0
        details["f_eps_next"] = f"{en['growth']:+.1f}% (est)"
    flags["price_below_mos"] = bool(a.get("price_below_mos"))

    # valuation inputs: latest fiscal year first (roe1 = most recent)
    years_desc = list(reversed(a.get("years") or []))[:5]
    roe, pay = a.get("roe_by_year") or {}, a.get("payout_by_year") or {}
    val_inputs = {
        "current_price": a.get("price"),
        "required_return": a.get("required_return", 10.0),
        "total_equity_m": round(a["latest_equity_m"], 4) if a.get("latest_equity_m") is not None else None,
        "shares_outstanding_m": round(a["shares_m"], 4) if a.get("shares_m") else None,
    }
    for i in range(1, 6):
        y = years_desc[i - 1] if i - 1 < len(years_desc) else None
        val_inputs[f"roe{i}"] = round(roe[y], 4) if (y in roe) else None
        val_inputs[f"payout{i}"] = round(pay[y] * 100.0, 4) if (y in pay) else None  # % for the form

    return {
        "ticker": a.get("ticker"),
        "company_name": a.get("company"),
        "financial": a.get("financial", False),
        "sic_desc": a.get("sic_desc"),
        "verdict": a.get("verdict"),
        "price": a.get("price"), "price_src": a.get("price_src"),
        "shares_src": a.get("shares_src"),
        "assessment": a["val"]["assessment"] if a.get("val") else None,
        "veto": a.get("veto", False), "veto_reason": a.get("veto_reason"),
        "eps_next": en,
        "flags": flags, "details": details,
        "valuation": val_inputs,
    }


# ─────────────────────── rendering ───────────────────────

def render(a):
    t = a["ticker"]
    if a.get("error"):
        print(f"\n{R}■ {t}{RST}  {a['error']}\n")
        return

    verdict = a["verdict"]
    vcol = G if verdict in ("CAN TRADE", "CAN INVEST") else (R if "VETO" in verdict else Y)
    if verdict.startswith("SKIP"):
        vcol = DIM
    print(f"\n{B}{'═'*66}{RST}")
    print(f"{B}■ {t}{RST}  {a['company'] or ''}  {DIM}(CIK {a['cik']}, FY{a['latest_fy']}){RST}")
    price = a["price"]
    print(f"  Price: {'$%.2f'%price if price else 'n/a'} {DIM}[{a['price_src'] or '—'}]{RST}"
          f"   →   {vcol}▶ {verdict}{RST}")
    print(f"{B}{'═'*66}{RST}")

    print(f"\n  {'FUNDAMENTALS':<30}  score {a['fund_score']}/10")
    for label, ok, detail in a["checks"]:
        mark = f"{G}✓{RST}" if ok else f"{R}✗{RST}"
        col = G if ok else R
        print(f"    {mark} {label:<30} {col}{detail}{RST}")

    # forward analyst estimate — shown but not scored / not in the trade gate
    en = a.get("eps_next") or {}
    if en.get("growth") is not None:
        ok = en["growth"] > 0
        mark, col = (f"{G}~{RST}", G) if ok else (f"{Y}~{RST}", Y)
        print(f"    {mark} {'EPS Growth Next Yr > 0%':<30} {col}{en['growth']:+.1f}%{RST} "
              f"{DIM}[{en['src']} est · not scored]{RST}")
    else:
        print(f"    {DIM}~ {'EPS Growth Next Yr > 0%':<30} n/a [estimate unavailable]{RST}")

    print(f"\n  {'VALUATION (equity multiple)':<30}")
    if a.get("financial"):
        print(f"    {Y}SKIPPED — financial sector ({a['sic_desc'] or 'SIC '+a['sic']}).{RST}")
        print(f"    {DIM}Equity-multiple model doesn't apply to banks/insurers; awaiting your method.{RST}")
    elif a["veto"]:
        print(f"    {R}VETOED — {a['veto_reason']}.{RST}")
        if a["val"]:
            print(f"    {DIM}(model output ${a['val']['val_mos']:.0f} MOS — ignore, not meaningful){RST}")
    elif not a["val"]:
        print(f"    {Y}skipped — missing price or ROE/shares data.{RST}")
    else:
        v = a["val"]
        acol = {"UNDERVALUED": G, "FAIR_VALUE": Y, "OVERVALUED": R}.get(v["assessment"], "")
        print(f"    Median ROE: {v['roe_median']:.1f}%   Book/share: ${v['eps_book']:.2f}")
        print(f"    MOS valuation:    ${v['val_mos']:.2f}   (discount {v['disc_mos']:+.1f}%)")
        print(f"    Median valuation: ${v['val_median']:.2f}   (discount {v['disc_median']:+.1f}%)")
        print(f"    Assessment: {acol}{v['assessment']}{RST}"
              f"   Price < MOS: {G+'yes'+RST if a['price_below_mos'] else R+'no'+RST}")

    if a["sm"] and a["sm"]["holders"]:
        top = ", ".join(f"{n} {w:.1f}%" for n, w in a["sm"]["top"])
        print(f"\n  {'SMART MONEY':<30}  {a['sm']['holders']} gurus, max {a['sm']['max_weight']:.1f}%")
        print(f"    {DIM}{top}{RST}")

    print(f"\n  {DIM}Check manually: {'; '.join(a['manual'])}{RST}")
    print()


def main():
    ap = argparse.ArgumentParser(description="Horizon research from SEC EDGAR")
    ap.add_argument("tickers", nargs="+", help="ticker symbols, e.g. GOOG AAPL")
    ap.add_argument("--price", type=float, default=None, help="override live price (applies to all)")
    ap.add_argument("--required", type=float, default=10.0, help="required return %% (default 10)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a report")
    args = ap.parse_args()

    results = []
    for i, tk in enumerate(args.tickers):
        if i:
            time.sleep(0.3)  # be polite to SEC (10 req/s limit)
        results.append(analyze(tk.strip().upper(), price_override=args.price, required=args.required))

    if args.json:
        # strip ANSI-only fields; checks tuple -> list
        for a in results:
            if "checks" in a:
                a["checks"] = [{"label": l, "pass": ok, "detail": d} for l, ok, d in a["checks"]]
        print(json.dumps(results, indent=2, default=str))
    else:
        for a in results:
            render(a)


if __name__ == "__main__":
    main()
