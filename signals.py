"""Signal engine — a pure-Python port of horizon_signal.pine.

Given daily OHLCV bars (oldest-first, from prices.fetch_history) it reproduces
the Research view's Technicals: Wilder RSI, Stochastic %K/%D, volume MA, and the
edge-triggered BUY / SELL conditions. Indicators are computed over the *whole*
series (long warmup) so Wilder smoothing converges to TradingView's Data Window
values; evaluate only fires on the recent bars.

Every threshold is a parameter (see DEFAULTS) so the app can be tuned to match
whatever you run on TradingView. DEFAULTS reflect the app author's live
TradingView config (RSI rising bars = 0, Trade sell = 60), not the Pine file's
literal input defaults.

Edge-trigger: a signal fires only on the first bar its condition goes true
(cond and not cond[-1]), exactly like the Pine `buyCond and not buyCond[1]`.
"""

# Defaults mirror the live TradingView setup. All are overridable via params.
DEFAULTS = {
    "rsi_length": 14,
    "buy_rsi_trade": 35,       # BUY: RSI max (Trade)
    "buy_rsi_invest": 40,      # BUY: RSI max (Invest)
    "rsi_rising_bars": 0,      # BUY: RSI rising bars (0 = off)
    "sell_rsi_trade": 60,      # SELL: RSI min (Trade)
    "sell_rsi_invest": 60,     # SELL: RSI min (Invest)
    "stoch_k_length": 14,
    "stoch_smooth_k": 1,
    "stoch_d_length": 3,
    "stoch_buy_max": 20,       # BUY: Stoch %D max
    "stoch_sell_min": 80,      # SELL: Stoch %D min
    "use_vol_filter": True,    # BUY: require volume > MA
    "vol_ma_length": 10,
}

# Value bounds, used by the API to validate user input.
PARAM_BOUNDS = {
    "rsi_length": (2, 50), "buy_rsi_trade": (1, 99), "buy_rsi_invest": (1, 99),
    "rsi_rising_bars": (0, 10), "sell_rsi_trade": (1, 99), "sell_rsi_invest": (1, 99),
    "stoch_k_length": (1, 50), "stoch_smooth_k": (1, 10), "stoch_d_length": (1, 10),
    "stoch_buy_max": (1, 99), "stoch_sell_min": (1, 99), "vol_ma_length": (1, 50),
}


def merged_params(params=None):
    """Fill missing keys from DEFAULTS; ignore unknown keys."""
    out = dict(DEFAULTS)
    if params:
        for k in DEFAULTS:
            if k in params and params[k] is not None:
                out[k] = params[k]
    return out


def _sma(vals, length):
    """Simple moving average aligned to vals; None until the window fills or on
    any None inside the window."""
    out = [None] * len(vals)
    for i in range(len(vals)):
        if i + 1 < length:
            continue
        window = vals[i - length + 1: i + 1]
        if any(v is None for v in window):
            continue
        out[i] = sum(window) / length
    return out


def _wilder_rsi(closes, length):
    """Wilder's RSI (matches Pine ta.rsi), aligned to closes; None during warmup."""
    n = len(closes)
    out = [None] * n
    if n <= length:
        return out
    gains, losses = [], []
    for i in range(1, n):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    # Seed averages with the SMA of the first `length` changes (deltas 0..len-1,
    # i.e. bars 1..len); first RSI value lands on bar index `length`.
    avg_gain = sum(gains[:length]) / length
    avg_loss = sum(losses[:length]) / length
    out[length] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1 + avg_gain / avg_loss)
    for i in range(length + 1, n):
        g, l = gains[i - 1], losses[i - 1]
        avg_gain = (avg_gain * (length - 1) + g) / length
        avg_loss = (avg_loss * (length - 1) + l) / length
        out[i] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1 + avg_gain / avg_loss)
    return out


def _stoch_k_raw(highs, lows, closes, length):
    """Raw %K = 100*(close-LL)/(HH-LL) over the window (Pine ta.stoch)."""
    n = len(closes)
    out = [None] * n
    for i in range(n):
        if i + 1 < length:
            continue
        hh = max(highs[i - length + 1: i + 1])
        ll = min(lows[i - length + 1: i + 1])
        rng = hh - ll
        out[i] = 0.0 if rng == 0 else 100.0 * (closes[i] - ll) / rng
    return out


def compute_indicators(bars, params=None):
    """Return {rsi, k, d, vol_ma} arrays aligned to bars (None during warmup)."""
    p = merged_params(params)
    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    vols = [b["volume"] for b in bars]
    rsi = _wilder_rsi(closes, p["rsi_length"])
    k_raw = _stoch_k_raw(highs, lows, closes, p["stoch_k_length"])
    k = _sma(k_raw, p["stoch_smooth_k"])
    d = _sma(k, p["stoch_d_length"])
    vol_ma = _sma(vols, p["vol_ma_length"])
    return {"rsi": rsi, "k": k, "d": d, "vol_ma": vol_ma}


def evaluate(bars, kind="Trade", params=None):
    """Per-bar signal series aligned to bars. Each element:
        {date, close, rsi, k, d, buy, sell}
    where buy/sell are edge-triggered booleans. `kind` picks the RSI thresholds.
    """
    p = merged_params(params)
    ind = compute_indicators(bars, p)
    rsi, k, d, vol_ma = ind["rsi"], ind["k"], ind["d"], ind["vol_ma"]
    buy_rsi_max = p["buy_rsi_trade"] if kind == "Trade" else p["buy_rsi_invest"]
    sell_rsi_min = p["sell_rsi_trade"] if kind == "Trade" else p["sell_rsi_invest"]
    trend_bars = p["rsi_rising_bars"]
    use_vol = p["use_vol_filter"]
    sto_buy_max = p["stoch_buy_max"]
    sto_sell_min = p["stoch_sell_min"]

    def rsi_up(j):
        if trend_bars <= 0:
            return True
        for i in range(trend_bars):
            a, b = rsi[j - i], rsi[j - i - 1]
            if a is None or b is None or not (a > b):
                return False
        return True

    buy_cond = [False] * len(bars)
    sell_cond = [False] * len(bars)
    for j, bar in enumerate(bars):
        if rsi[j] is None or k[j] is None or d[j] is None:
            continue
        vol_ok = (not use_vol) or (vol_ma[j] is not None and bar["volume"] > vol_ma[j])
        buy_cond[j] = (rsi[j] < buy_rsi_max and rsi_up(j)
                       and d[j] < sto_buy_max and k[j] > d[j] and vol_ok)
        sell_cond[j] = (rsi[j] > sell_rsi_min and d[j] > sto_sell_min and k[j] < d[j])

    out = []
    for j, bar in enumerate(bars):
        buy_sig = buy_cond[j] and not (j > 0 and buy_cond[j - 1])
        sell_sig = sell_cond[j] and not (j > 0 and sell_cond[j - 1])
        out.append({
            "date": bar["date"], "close": bar["close"],
            "rsi": rsi[j], "k": k[j], "d": d[j],
            "buy": buy_sig, "sell": sell_sig,
        })
    return out
