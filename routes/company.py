"""Company info lookup: ticker -> {company_name, sector, industry}.

Lookup order:
  1) horizon.db: latest trade (has sector/industry), then researched_stock (name only)
  2) smart_money.db: holdings.issuer (name only)
  3) SEC EDGAR: company_tickers.json -> CIK, submissions JSON -> sicDescription

Results are cached per-ticker in horizon.db.company_info_cache.
"""
import json
import time
import datetime as dt
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from flask import Blueprint, jsonify, request

from db import get_db, get_sm_db
from config import BASE_DIR

# smart_money config is vendored; reuse its sec_identity helper
try:
    from smart_money.smart_money.config import get_sec_identity
except Exception:
    def get_sec_identity():
        return None


bp = Blueprint("company", __name__)

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

CACHE_DIR = BASE_DIR / "data" / "cache"
TICKERS_CACHE = CACHE_DIR / "sec_company_tickers.json"
TICKERS_TTL_SECONDS = 7 * 24 * 3600  # refresh weekly


# SIC 2-digit prefix -> (sector, fallback industry). sicDescription overrides industry when present.
SIC_SECTOR_MAP = {
    "01": "Agriculture", "02": "Agriculture", "07": "Agriculture", "08": "Agriculture", "09": "Agriculture",
    "10": "Materials", "12": "Energy", "13": "Energy", "14": "Materials",
    "15": "Industrials", "16": "Industrials", "17": "Industrials",
    "20": "Consumer Staples", "21": "Consumer Staples",
    "22": "Consumer Discretionary", "23": "Consumer Discretionary",
    "24": "Materials", "25": "Consumer Discretionary", "26": "Materials", "27": "Communication Services",
    "28": "Materials",  # 283x pharma overridden below
    "29": "Energy",
    "30": "Materials", "31": "Consumer Discretionary", "32": "Materials", "33": "Materials", "34": "Materials",
    "35": "Industrials", "36": "Technology", "37": "Industrials", "38": "Health Care", "39": "Consumer Discretionary",
    "40": "Industrials", "41": "Industrials", "42": "Industrials", "44": "Industrials", "45": "Industrials",
    "46": "Energy", "47": "Industrials",
    "48": "Communication Services", "49": "Utilities",
    "50": "Industrials", "51": "Industrials",
    "52": "Consumer Discretionary", "53": "Consumer Discretionary", "54": "Consumer Staples",
    "55": "Consumer Discretionary", "56": "Consumer Discretionary", "57": "Consumer Discretionary",
    "58": "Consumer Discretionary", "59": "Consumer Discretionary",
    "60": "Financials", "61": "Financials", "62": "Financials", "63": "Financials", "64": "Financials",
    "65": "Real Estate", "67": "Financials",
    "70": "Consumer Discretionary", "72": "Consumer Discretionary",
    "73": "Technology", "75": "Consumer Discretionary", "76": "Consumer Discretionary",
    "78": "Communication Services", "79": "Communication Services",
    "80": "Health Care", "82": "Consumer Discretionary", "83": "Health Care", "87": "Industrials", "89": "Industrials",
}


def _sector_for_sic(sic: str | None) -> str | None:
    if not sic:
        return None
    s = str(sic).zfill(4)
    # Specific overrides
    if s.startswith("283"):
        return "Health Care"  # pharma / biotech
    if s.startswith("357"):
        return "Technology"  # computer & office equipment
    if s.startswith("367"):
        return "Technology"  # semiconductors
    if s.startswith("372") or s.startswith("376"):
        return "Industrials"  # aerospace
    if s.startswith("371"):
        return "Consumer Discretionary"  # motor vehicles
    return SIC_SECTOR_MAP.get(s[:2])


def _user_agent() -> str:
    ident = get_sec_identity() or "anonymous@example.com"
    return f"Horizon research dashboard {ident}"


def _http_get_json(url: str, timeout: int = 15):
    req = Request(url, headers={"User-Agent": _user_agent(), "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _load_tickers_index() -> dict:
    """Return {TICKER_UPPER: {cik, title}}. Cached on disk; refresh weekly."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fresh = False
    if TICKERS_CACHE.exists():
        age = time.time() - TICKERS_CACHE.stat().st_mtime
        if age < TICKERS_TTL_SECONDS:
            fresh = True
    if not fresh:
        try:
            data = _http_get_json(SEC_TICKERS_URL)
            TICKERS_CACHE.write_text(json.dumps(data))
        except (URLError, HTTPError, TimeoutError, json.JSONDecodeError):
            if not TICKERS_CACHE.exists():
                return {}
    try:
        raw = json.loads(TICKERS_CACHE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    index = {}
    for _, row in raw.items():
        t = str(row.get("ticker", "")).upper()
        if t:
            index[t] = {"cik": str(row.get("cik_str", "")).zfill(10), "title": row.get("title", "")}
    return index


def _lookup_horizon(ticker: str):
    with get_db() as db:
        row = db.execute(
            "SELECT company_name, sector, industry FROM trades "
            "WHERE ticker = ? AND (sector IS NOT NULL OR industry IS NOT NULL OR company_name IS NOT NULL) "
            "ORDER BY id DESC LIMIT 1",
            (ticker,),
        ).fetchone()
        if row and (row["sector"] or row["industry"] or row["company_name"]):
            return {
                "company_name": row["company_name"] or None,
                "sector": row["sector"] or None,
                "industry": row["industry"] or None,
                "source": "horizon:trades",
            }
        row = db.execute(
            "SELECT company_name FROM researched_stocks WHERE ticker = ? AND company_name IS NOT NULL "
            "ORDER BY id DESC LIMIT 1",
            (ticker,),
        ).fetchone()
        if row and row["company_name"]:
            return {"company_name": row["company_name"], "sector": None, "industry": None, "source": "horizon:research"}
    return None


def _lookup_smart_money(ticker: str):
    try:
        with get_sm_db() as sm:
            row = sm.execute(
                "SELECT issuer FROM holdings WHERE ticker = ? AND issuer IS NOT NULL "
                "ORDER BY report_period DESC LIMIT 1",
                (ticker,),
            ).fetchone()
            if row and row["issuer"]:
                return {"company_name": row["issuer"], "sector": None, "industry": None, "source": "smart_money"}
    except Exception:
        return None
    return None


def _lookup_sec(ticker: str):
    index = _load_tickers_index()
    entry = index.get(ticker)
    if not entry:
        return None
    cik = entry["cik"]
    title = entry.get("title") or None
    sector = None
    industry = None
    try:
        sub = _http_get_json(SEC_SUBMISSIONS_URL.format(cik=cik))
        industry = sub.get("sicDescription") or None
        sector = _sector_for_sic(sub.get("sic"))
        # Prefer the more formal name from submissions if available
        title = sub.get("name") or title
    except (URLError, HTTPError, TimeoutError, json.JSONDecodeError):
        pass
    return {
        "company_name": title.title() if isinstance(title, str) and title.isupper() else title,
        "sector": sector,
        "industry": industry,
        "cik": cik,
        "source": "sec",
    }


_NAME_ACRONYMS = {"LLC", "PLC", "LP", "LLP", "NA", "NV", "SA", "AG", "AB", "ASA", "PBC", "USA", "US", "UK", "REIT", "ETF", "II", "III", "IV", "V", "VI", "AT&T", "&"}


def _smart_title_case(name: str | None) -> str | None:
    if not name or not isinstance(name, str):
        return name
    if not name.isupper():
        return name
    parts = []
    for word in name.split():
        bare = word.strip(",.&/-")
        if bare in _NAME_ACRONYMS:
            parts.append(word)
        else:
            parts.append(word.title())
    return " ".join(parts)


def _merge(*results):
    """Combine partial results from different sources, first non-empty wins per field."""
    merged = {"company_name": None, "sector": None, "industry": None, "cik": None, "source": None}
    sources = []
    for r in results:
        if not r:
            continue
        sources.append(r.get("source"))
        for k in ("company_name", "sector", "industry", "cik"):
            if not merged[k] and r.get(k):
                merged[k] = r[k]
    merged["source"] = ",".join(s for s in sources if s) or None
    merged["company_name"] = _smart_title_case(merged["company_name"])
    return merged


def _read_cache(ticker: str):
    with get_db() as db:
        row = db.execute(
            "SELECT company_name, sector, industry, cik, source, fetched_at FROM company_info_cache WHERE ticker = ?",
            (ticker,),
        ).fetchone()
        return dict(row) if row else None


def _write_cache(ticker: str, info: dict):
    with get_db() as db:
        db.execute(
            "INSERT INTO company_info_cache (ticker, company_name, sector, industry, cik, source, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(ticker) DO UPDATE SET company_name=excluded.company_name, sector=excluded.sector, "
            "industry=excluded.industry, cik=excluded.cik, source=excluded.source, fetched_at=excluded.fetched_at",
            (
                ticker, info.get("company_name"), info.get("sector"), info.get("industry"),
                info.get("cik"), info.get("source"), dt.datetime.utcnow().isoformat(timespec="seconds"),
            ),
        )


@bp.route("/<ticker>", methods=["GET"])
def lookup(ticker):
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return jsonify({"success": False, "error": "ticker required"}), 400
    refresh = request.args.get("refresh") == "1"

    if not refresh:
        cached = _read_cache(ticker)
        if cached and (cached.get("company_name") or cached.get("sector") or cached.get("industry")):
            cached["ticker"] = ticker
            cached["cached"] = True
            return jsonify({"success": True, "data": cached})

    horizon = _lookup_horizon(ticker)
    sm = _lookup_smart_money(ticker)
    sec = _lookup_sec(ticker)
    merged = _merge(horizon, sm, sec)
    merged["ticker"] = ticker
    merged["cached"] = False
    if merged["company_name"] or merged["sector"] or merged["industry"]:
        _write_cache(ticker, merged)
        return jsonify({"success": True, "data": merged})
    return jsonify({"success": True, "data": {"ticker": ticker, "company_name": None, "sector": None, "industry": None, "source": None, "cached": False}})
