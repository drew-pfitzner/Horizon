"""Daily OHLCV history fetch for the alert engine (free, no API key).

Separate from research_cli.fetch_price, which returns a single last-quote
scalar. The signal engine needs full daily OHLCV history with enough warmup
for Wilder's RSI / Stoch smoothing to converge to TradingView's values, so we
pull ~2y by default. Primary source is the Yahoo chart API; Stooq's daily
history CSV is the fallback.

A Bar is a dict: {date: 'YYYY-MM-DD', open, high, low, close, volume}. Bars are
returned oldest-first (chronological), which is what signals.py expects.
"""
import csv
import io
import json
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

YAHOO_HIST_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
    "?interval=1d&range={range}"
)
STOOQ_HIST_URL = "https://stooq.com/q/d/l/?s={sym}.us&i=d"
_UA = "Horizon alerts drew.pfitzner@gmail.com"


def _http(url, timeout=20):
    req = Request(url, headers={"User-Agent": _UA})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def _from_yahoo(ticker, rng):
    raw = json.loads(_http(YAHOO_HIST_URL.format(sym=ticker, range=rng)))
    res = raw["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    opens, highs = q["open"], q["high"]
    lows, closes, vols = q["low"], q["close"], q["volume"]
    bars = []
    for i, t in enumerate(ts):
        o, h, l, c, v = opens[i], highs[i], lows[i], closes[i], vols[i]
        # Yahoo emits nulls for holidays / in-progress bars — skip incomplete rows.
        if None in (o, h, l, c):
            continue
        d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        bars.append({
            "date": d, "open": float(o), "high": float(h),
            "low": float(l), "close": float(c),
            "volume": float(v) if v is not None else 0.0,
        })
    return bars


def _from_stooq(ticker):
    text = _http(STOOQ_HIST_URL.format(sym=ticker.lower()))
    reader = csv.DictReader(io.StringIO(text))
    bars = []
    for row in reader:
        try:
            bars.append({
                "date": row["Date"], "open": float(row["Open"]),
                "high": float(row["High"]), "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row.get("Volume") or 0.0),
            })
        except (KeyError, ValueError):
            continue
    return bars


def fetch_history(ticker, rng="2y"):
    """Full daily OHLCV history, oldest-first. Yahoo primary, Stooq fallback.

    Returns (bars, source). bars is [] and source is None if both fail — the
    caller logs the failure so a silently-dead ticker stays diagnosable.
    """
    ticker = ticker.upper()
    try:
        bars = _from_yahoo(ticker, rng)
        if bars:
            return bars, "yahoo"
    except (URLError, HTTPError, TimeoutError, ValueError, KeyError, TypeError, IndexError):
        pass
    try:
        bars = _from_stooq(ticker)
        if bars:
            return bars, "stooq"
    except (URLError, HTTPError, TimeoutError, ValueError, KeyError):
        pass
    return [], None
