"""Signal engine — a pure-Python port of horizon_signal.pine.

Given daily OHLCV bars (oldest-first, from prices.fetch_history) it reproduces
the Research view's Technicals: Wilder RSI(14), Stochastic %K/%D (14/1/3),
volume MA(10), and the edge-triggered BUY / SELL conditions. Indicators are
computed over the *whole* series (long warmup) so Wilder smoothing converges to
TradingView's Data Window values; evaluate only fires on the recent bars.

Thresholds mirror the Pine inputs:
  BUY : RSI < 35 (Trade) / 40 (Invest), RSI rising N bars, %D < 20, %K > %D, volOk
  SELL: RSI > 55 (Trade) / 60 (Invest),                    %D > 80, %K < %D
Edge-trigger: a signal fires only on the first bar its condition goes true
(cond and not cond[-1]), exactly like the Pine `buyCond and not buyCond[1]`.
"""

RSI_LEN = 14
STO_K = 14
STO_SMOOTH_K = 1
STO_D = 3
VOL_MA_LEN = 10

BUY_RSI_MAX = {"Trade": 35, "Invest": 40}
SELL_RSI_MIN = {"Trade": 55, "Invest": 60}
STO_BUY_MAX = 20
STO_SELL_MIN = 80


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


def _wilder_rsi(closes, length=RSI_LEN):
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


def _stoch_k_raw(highs, lows, closes, length=STO_K):
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


def compute_indicators(bars):
    """Return {rsi, k, d, vol_ma} arrays aligned to bars (None during warmup)."""
    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    vols = [b["volume"] for b in bars]
    rsi = _wilder_rsi(closes)
    k_raw = _stoch_k_raw(highs, lows, closes)
    k = _sma(k_raw, STO_SMOOTH_K)  # len 1 → equals k_raw where present
    d = _sma(k, STO_D)
    vol_ma = _sma(vols, VOL_MA_LEN)
    return {"rsi": rsi, "k": k, "d": d, "vol_ma": vol_ma}


def evaluate(bars, kind="Trade", use_vol=True, rsi_trend_bars=2):
    """Per-bar signal series aligned to bars. Each element:
        {date, close, rsi, k, d, buy, sell}
    where buy/sell are edge-triggered booleans. `kind` picks the RSI thresholds.
    """
    ind = compute_indicators(bars)
    rsi, k, d, vol_ma = ind["rsi"], ind["k"], ind["d"], ind["vol_ma"]
    buy_rsi_max = BUY_RSI_MAX.get(kind, BUY_RSI_MAX["Trade"])
    sell_rsi_min = SELL_RSI_MIN.get(kind, SELL_RSI_MIN["Trade"])

    def rsi_up(j):
        if rsi_trend_bars <= 0:
            return True
        for i in range(rsi_trend_bars):
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
                       and d[j] < STO_BUY_MAX and k[j] > d[j] and vol_ok)
        sell_cond[j] = (rsi[j] > sell_rsi_min and d[j] > STO_SELL_MIN and k[j] < d[j])

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
