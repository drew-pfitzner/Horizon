"""Live fetch for the six Market Check indicators — free sources, no API keys.

Replaces the daily copy-off-the-screen routine (CNN Fear & Greed, FRED, and
reading RSI / Stoch / S5FI off TradingView). Every source here is a public
endpoint; nothing is scraped from a chart.

  St. Louis Fed (STLFSI4)  FRED CSV download       weekly series
  VIX                      Yahoo ^VIX              last completed daily bar
  RSI / Stochastic         computed from ^GSPC     signals.compute_indicators
  S5FI (% above 50DMA)     computed from the 500   expensive — cached, see below
  Fear & Greed             CNN dataviz JSON        needs browser-ish headers

RSI and Stochastic are *computed*, not read: signals.py is already a faithful
port of the TradingView indicators, so ^GSPC bars through compute_indicators
reproduce the chart's Data Window values exactly (verified to 2dp against the
live chart). Stochastic reports %D, the line the gate thresholds describe.

S5FI has no free feed — TradingView's INDEX:S5FI is licensed — so we rebuild it
from the constituents: pull the S&P 500 list, fetch 6 months of daily closes for
each via Yahoo's multi-symbol `spark` endpoint (20 symbols per call, the server's
hard cap), and count how many closed above their own 50-day SMA. That is ~26
paced requests and takes a minute or two, so it is cached per trading day and
refreshed by a background job, never inline in a request.
"""
import csv
import io
import json
import re
import time
from datetime import datetime, date, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from prices import fetch_history
from signals import compute_indicators
from db import get_setting, set_setting

# CNN's edge rejects anything that doesn't look like the page's own XHR.
_BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={start}"
CNN_FG = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
WIKI_SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
YAHOO_SPARK = ("https://query1.finance.yahoo.com/v7/finance/spark"
               "?symbols={syms}&range=6mo&interval=1d")

SPARK_BATCH = 20        # Yahoo 400s above this many symbols per call
SPARK_PAUSE = 1.5       # seconds between batches; faster trips a 429 cooldown
SPARK_RETRIES = 3
SPX_SYMBOL = "^GSPC"
VIX_SYMBOL = "^VIX"
MARKET_CLOSE_HOUR = 16  # ET; today's daily bar isn't final before this

_NET_ERRORS = (URLError, HTTPError, TimeoutError, ValueError, KeyError,
               TypeError, IndexError)


def _http(url, timeout=30, browser=False):
    ua = _BROWSER_UA if browser else "Horizon market-check"
    headers = {"User-Agent": ua}
    if browser:
        headers.update({
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://edition.cnn.com/markets/fear-and-greed",
            "Origin": "https://edition.cnn.com",
        })
    with urlopen(Request(url, headers=headers), timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _ok(value, source, as_of, **extra):
    d = {"value": value, "source": source, "as_of": as_of, "error": None}
    d.update(extra)
    return d


def _err(source, message):
    return {"value": None, "source": source, "as_of": None, "error": message}


# ─────────────────────────── individual indicators ───────────────────────────

def fetch_stl_fed(series="STLFSI4"):
    """Latest St. Louis Fed Financial Stress Index observation.

    Weekly series (Friday-dated), so the newest value is usually a few days old
    — that is the series, not a staleness bug. Requesting the full history times
    out on FRED's side; a 180-day window returns instantly.
    """
    start = (date.today() - timedelta(days=180)).isoformat()
    try:
        text = _http(FRED_CSV.format(series=series, start=start))
    except _NET_ERRORS as e:
        return _err("fred", f"FRED fetch failed: {e}")
    rows = [r for r in csv.reader(io.StringIO(text)) if len(r) >= 2]
    for obs_date, raw in reversed(rows[1:]):
        try:
            return _ok(round(float(raw), 4), "fred", obs_date)
        except ValueError:
            continue  # FRED writes "." for missing observations
    return _err("fred", "no numeric observations in the last 180 days")


def _last_completed_bars(bars, now_et=None):
    """Drop today's in-progress bar, mirroring alert_job._completed_bars."""
    from alert_job import ET
    now_et = now_et or datetime.now(ET)
    if bars and bars[-1]["date"] == now_et.strftime("%Y-%m-%d") \
            and now_et.hour < MARKET_CLOSE_HOUR:
        return bars[:-1]
    return bars


def fetch_vix():
    bars, source = fetch_history(VIX_SYMBOL, rng="1mo")
    bars = _last_completed_bars(bars) if bars else []
    if not bars:
        return _err("yahoo", "VIX price fetch failed")
    last = bars[-1]
    return _ok(round(last["close"], 2), source, last["date"])


def fetch_spx_technicals(params=None):
    """RSI and Stochastic %K/%D for the S&P 500, computed from daily bars.

    Uses the same engine as the alert signals, so these match the TradingView
    panes the Market Check numbers used to be copied from.
    """
    bars, source = fetch_history(SPX_SYMBOL, rng="2y")
    bars = _last_completed_bars(bars) if bars else []
    if len(bars) < 60:
        return _err("yahoo", "S&P 500 price fetch failed"), _err("yahoo", "S&P 500 price fetch failed")
    ind = compute_indicators(bars, params)
    as_of = bars[-1]["date"]
    rsi, k, d = ind["rsi"][-1], ind["k"][-1], ind["d"][-1]
    if rsi is None or d is None:
        return _err(source, "not enough history to compute"), _err(source, "not enough history to compute")
    # The gate's Stochastic thresholds (≤20 / ≥80) describe %D — the same line
    # signals.py gates on — so %D is the value; %K rides along for context.
    return (_ok(round(rsi, 2), source, as_of, symbol=SPX_SYMBOL),
            _ok(round(d, 2), source, as_of, symbol=SPX_SYMBOL,
                k=round(k, 2) if k is not None else None))


def fetch_fear_greed():
    try:
        raw = json.loads(_http(CNN_FG, browser=True))
        fg = raw["fear_and_greed"]
        ts = (fg.get("timestamp") or "")[:10] or None
        return _ok(round(float(fg["score"]), 2), "cnn", ts,
                   rating=fg.get("rating"),
                   previous_close=fg.get("previous_close"))
    except _NET_ERRORS as e:
        return _err("cnn", f"CNN Fear & Greed fetch failed: {e}")


# ─────────────────────────── S5FI (computed) ───────────────────────────

_TAG = re.compile(r"<[^>]+>")


def _parse_constituents(html):
    """Tickers from the Wikipedia constituents table.

    Wikipedia serves two different HTML flavours for the same page depending on
    which renderer answers, so this reads generically: first cell of every row
    in the #constituents table, tags stripped, kept if it looks like a ticker.
    """
    i = html.find('id="constituents"')
    if i < 0:
        return []
    table = html[i:html.find("</table>", i)]
    out = []
    for row in re.split(r"<tr[^>]*>", table)[1:]:
        cells = re.split(r"<td[^>]*>", row)
        if len(cells) < 2:
            continue
        text = _TAG.sub("", cells[1].split("</td>")[0]).strip()
        if re.fullmatch(r"[A-Z][A-Z.\-]{0,5}", text):
            out.append(text)
    return list(dict.fromkeys(out))


def sp500_constituents(max_age_days=7):
    """Cached S&P 500 ticker list. Falls back to the last good cache if the
    Wikipedia page fails or its markup changes, so S5FI keeps working."""
    cache = get_setting("sp500_constituents", {}) or {}
    cached = cache.get("symbols") or []
    fetched = cache.get("fetched_at", "")[:10]
    if cached and fetched:
        try:
            age = (date.today() - date.fromisoformat(fetched)).days
            if age < max_age_days:
                return cached, "cache"
        except ValueError:
            pass
    try:
        syms = _parse_constituents(_http(WIKI_SP500, timeout=30, browser=True))
    except _NET_ERRORS:
        syms = []
    if len(syms) >= 400:
        set_setting("sp500_constituents", {
            "symbols": syms,
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
        })
        return syms, "wikipedia"
    if cached:
        return cached, "cache (stale)"
    return [], None


def compute_s5fi(log=None):
    """% of S&P 500 members closing above their own 50-day SMA.

    Slow by nature (~26 paced Yahoo calls). Call it from a background job, not
    from a request handler. Returns the same dict shape as the fetchers.
    """
    def say(msg):
        if log:
            log(msg)

    syms, list_source = sp500_constituents()
    if not syms:
        return _err("computed", "could not get the S&P 500 constituent list")
    say(f"{len(syms)} constituents ({list_source})")

    # Yahoo wants BRK-B where the index lists BRK.B.
    yahoo_syms = [s.replace(".", "-") for s in syms]
    closes, failed = {}, []
    for i in range(0, len(yahoo_syms), SPARK_BATCH):
        batch = yahoo_syms[i:i + SPARK_BATCH]
        url = YAHOO_SPARK.format(syms=",".join(batch))
        payload = None
        for attempt in range(SPARK_RETRIES):
            try:
                payload = json.loads(_http(url, timeout=30))
                break
            except _NET_ERRORS:
                # A burst trips a rate-limit cooldown; back off rather than hammer.
                time.sleep(5 * (attempt + 1))
        if payload is None:
            failed.extend(batch)
            say(f"batch {i // SPARK_BATCH + 1}: fetch failed")
            continue
        for item in payload.get("spark", {}).get("result", []):
            try:
                quote = item["response"][0]["indicators"]["quote"][0]["close"]
                series = [c for c in quote if c is not None]
                if len(series) >= 51:
                    closes[item["symbol"]] = series
            except (KeyError, IndexError, TypeError):
                continue
        say(f"batch {i // SPARK_BATCH + 1}/{(len(yahoo_syms) - 1) // SPARK_BATCH + 1}: "
            f"{len(closes)} with history")
        time.sleep(SPARK_PAUSE)

    if len(closes) < 400:
        return _err("computed",
                    f"only {len(closes)} of {len(syms)} constituents returned usable "
                    f"history — too few to trust the reading")

    above = sum(1 for s in closes.values() if s[-1] > sum(s[-50:]) / 50)
    value = round(100.0 * above / len(closes), 2)
    as_of = _latest_spx_bar()
    say(f"S5FI = {value} ({above}/{len(closes)} above their 50DMA)")
    return _ok(value, "computed", as_of, universe=len(closes), missing=len(failed))


def _latest_spx_bar():
    """Bar date the S5FI reading belongs to — the index's last completed close."""
    bars, _ = fetch_history(SPX_SYMBOL, rng="1mo")
    bars = _last_completed_bars(bars) if bars else []
    return bars[-1]["date"] if bars else date.today().isoformat()


def cached_s5fi():
    """Last computed S5FI plus whether it belongs to the latest closed bar."""
    cache = get_setting("s5fi_cache", None)
    if not cache or cache.get("value") is None:
        return None, True
    latest = _latest_spx_bar()
    return cache, cache.get("as_of") != latest


def store_s5fi(result):
    if result.get("value") is not None:
        set_setting("s5fi_cache", {
            "value": result["value"],
            "as_of": result["as_of"],
            "source": "computed",
            "universe": result.get("universe"),
            "computed_at": datetime.now().isoformat(timespec="seconds"),
        })
    return result


# ─────────────────────────── the snapshot ───────────────────────────

def snapshot(include_s5fi=True):
    """All six indicators, each as {value, source, as_of, error}.

    Fast: four network calls, none of them S5FI — that comes from the cache with
    a `stale` flag so the caller can decide whether to kick off a recompute.
    """
    stl = fetch_stl_fed()
    vix = fetch_vix()
    rsi, stoch = fetch_spx_technicals(get_setting("alert_signal", None))
    fg = fetch_fear_greed()

    out = {
        "st_louis_fed": stl,
        "vix": vix,
        "rsi": rsi,
        "stochastic": stoch,
        "fear_greed": fg,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if include_s5fi:
        cache, stale = cached_s5fi()
        if cache:
            out["s5fi"] = _ok(cache["value"], "computed (cached)", cache.get("as_of"),
                              stale=stale, computed_at=cache.get("computed_at"),
                              universe=cache.get("universe"))
        else:
            out["s5fi"] = dict(_err("computed", "not computed yet"), stale=True)
    return out


def to_form(snap):
    """Snapshot → the six market_check fields, dropping anything that failed."""
    return {k: snap[k]["value"] for k in
            ("st_louis_fed", "vix", "rsi", "stochastic", "s5fi", "fear_greed")
            if snap.get(k) and snap[k].get("value") is not None}
