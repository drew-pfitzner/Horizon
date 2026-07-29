# Horizon Self-Hosted Alerts — Build Plan

**Goal:** Replace TradingView alerts (whose free-plan 1-month expiration is too short for
long-held trades) with a self-hosted alert engine inside the Horizon Docker app that pushes
buy/sell signals to your phone. Must work end-of-day AND catch up on server startup/resume
(so it's usable by people who don't run the box 24/7).

**Status:** Built (2026-07-30). Transport: **ntfy**. Engine validated (Wilder RSI matches a
reference impl exactly; dedupe/resume confirmed; real ntfy pushes delivered). Configure a topic
in the Alerts view and enable to go live.

---

## UX shape (what the user sees)

A new **Alerts** tab sits between **Research** and **Trades** in the nav
(`templates/index.html`, between lines 25–26; route in `static/js/app.js`).

The Alerts view has **two lists**:

- **Buy** — tickers you want to *open* a position in. Watched for **BUY signals only**.
- **Held** — tickers you already own. Watched for **BOTH** directions:
  - a **BUY** signal → "add to the position"
  - a **SELL** signal → "sell it out"

Two one-click flows tie it into the rest of the app:

1. **Add to Buy from Research.** A button in the Research view ("★ Watch to Buy") inserts the
   current ticker into the Buy list, carrying `kind` from the research decision
   (TRADE → `Trade`, INVEST → `Invest`). No retype.
2. **Move Buy → Held in Alerts.** Each Buy row has a one-tap **"Now holding"** button that
   flips its bucket to Held (so it starts watching for add/sell signals too). This is the
   natural action the moment you actually buy. (A reverse "Back to Buy" is trivial to add.)

So the bucket, not a free-form direction, is the primary concept. Directions watched are
*derived* from the bucket:

| Bucket | Signals watched |
|--------|-----------------|
| Buy    | BUY             |
| Held   | BUY (add) + SELL |

---

## Notifications (simple, says bucket + signal)

One line, unambiguous about **which list** and **which signal**:

```
Buy list  + BUY  →  Title: "Horizon · BUY — AAPL"          Body: "@ 340.08 · RSI 32, %D 18"
Held list + BUY  →  Title: "Horizon · HELD · ADD — AAPL"   Body: "@ 340.08 · RSI 32, %D 18"
Held list + SELL →  Title: "Horizon · HELD · SELL — AAPL"  Body: "@ 361.40 · RSI 62, %D 84"
```

- The **bucket** (BUY / HELD) tells you whether this is a new entry or an existing position.
- The **action** (BUY / ADD / SELL) tells you what the signal wants.
- `kind` (Trade/Invest) rides along only in the body if it matters, to keep the title short.

---

## Feasibility: confirmed (with corrections)

The reusable parts in the repo:
- `sm_job.py` is the exact background-thread pattern to reuse for the scheduler (incl. its
  `_state_lock` / `is_running()` single-flight guard — needed so "Check now" and the timer
  can't overlap).
- `horizon_signal.pine` is the signal spec to port.
- Seed sources are real columns: open positions via `trades.exit_date IS NULL`; research
  decisions via `researched_stocks.decision` ∈ TRADE/INVEST/NO_ACTION.

**Correction — the data layer does NOT already exist.** The plan previously claimed
`research_cli.py`'s `fetch_price` gives us history. It does not:
- `YAHOO_URL` is hardcoded to `interval=1d&range=1d` (`research_cli.py:52`) — one bar.
- `fetch_price` returns a single scalar (`regularMarketPrice`/`previousClose`), not OHLCV.
- Its Stooq fallback parses only the latest row — so it is not a history fallback either.

We must write a **new** `fetch_history(ticker)` (see below). Budget it as net-new, not reuse.

Delayed data is fine because these are **daily-close** signals, not intraday.

---

## The pieces

### 1. Data source — new `fetch_history(ticker)` (free, no key)
- Primary: Yahoo chart `.../chart/{TICKER}?interval=1d&range=2y` →
  `timestamp[]` + `indicators.quote[0].{open,high,low,close,volume}` → OHLCV array.
- **Fetch ~1–2y, not 3mo.** Wilder's RSI/Stoch smoothing is recursive and seeded from the
  *start* of the series; TradingView computes over the full loaded chart. With only ~62 bars
  (3mo) the smoothing hasn't converged and our RSI will disagree with the Data Window during
  validation. Fetch long history for warmup, compute indicators over the whole series, then
  evaluate only the recent/missed bars.
- Fallback: Stooq **history** CSV (`stooq.com/q/d/l/?s={sym}&i=d`) — a *different* call than the
  single-quote one in `fetch_price`; parse all rows into the same OHLCV shape.
- One call per ticker per run; cache to stay polite. Yahoo is unofficial → rate-limit/format
  risk mitigated by low volume + Stooq fallback.

### 2. Signal engine — `signals.py` (new, pure Python, stdlib only)
Port `horizon_signal.pine` exactly:
- **RSI**: Wilder's smoothing (matches `ta.rsi`), length 14.
- **Stochastic**: raw %K = `ta.stoch(close,high,low,14)`, SMA smooth %K (len 1), SMA %D (len 3).
- **Volume**: `volume > SMA(volume, 10)` (buy only, optional).
- **Buy thresholds**: RSI < 35 (Trade) / < 40 (Invest); RSI rising for N bars (default 2);
  %D < 20; %K > %D; volOk.
- **Sell thresholds**: RSI > 55 (Trade) / > 60 (Invest); %D > 80; %K < %D.
- **Edge-trigger**: fire on the first bar all conditions go true (`cond and not cond[1]`).
- Pure function over the OHLCV array → returns, for a given bar, whether BUY and/or SELL fired.
- **Validate against the Pine script's Data Window** before building anything else — with 2y of
  warmup history, RSI/%K/%D must match to reasonable precision.

### 3. What it watches — `alert_watch` table (bucket-based)
```
alert_watch(
  id INTEGER PK,
  ticker TEXT,
  bucket TEXT,          -- BUY | HELD
  kind   TEXT,          -- Trade | Invest
  active INTEGER DEFAULT 1,
  created_at TEXT,
  UNIQUE(ticker)        -- one row per ticker; moving Buy→Held just flips bucket
)
```
Directions watched are derived from `bucket` (BUY→[BUY]; HELD→[BUY,SELL]); we do not store a
free-form direction.

Auto-seed suggestions from existing data (user confirms/edits in the Alerts view):
- `researched_stocks` with decision TRADE/INVEST → suggest for the **Buy** list.
- Open trades (`trades.exit_date IS NULL`) → suggest for the **Held** list.

### 4. When it runs (solves the TradingView-expiry problem)
- **Timer** (background thread, sm_job pattern): wakes after US close, evaluates the
  just-closed daily bar.
- **Timezone-correct.** The Docker container clock is UTC (a local Mac is Pacific), so "after
  4pm ET close" and the `alert_check_time` setting must be computed in **US/Eastern**, and the
  "latest completed bar" must be an ET market date. Bar-date dedupe stops duplicates but does
  NOT stop evaluating a bar too early — so the close check is explicit ET logic, not naive
  local time.
- **On startup/resume**: on boot, compare each ticker's latest completed bar vs stored
  `last_signaled_bar_date`; catch up on anything missed while the box was off. This is what
  makes it work for non-24/7 users.
- **Manual "Check now"** button (like smart-money update).
- **No holiday calendar needed**: signals key off the bar date; weekends/holidays have no new
  bar → nothing fires. Same bar-date dedupe prevents duplicate alerts across restarts.
- Never expires — re-derives from live data every run (unlike TradingView's 1-month cap).

### 5. Notification transport — ntfy (chosen)
- Free, no account. Install ntfy app, subscribe to a secret topic; server POSTs to it.
- Server/topic **configurable**: start on `ntfy.sh` with a long random topic; later drop a
  self-hosted ntfy container into compose with no code change.
- **Fits the Tailscale model**: the box POSTs *outbound* to ntfy.sh and the phone subscribes —
  nothing about the box is publicly exposed.
- Push happens at the moment a signal fires → reaches you even if the box was just turned on.
- **Privacy note:** public ntfy.sh topics are readable by anyone who knows the topic name —
  use a long random topic, or self-host for full privacy.

---

## Build order

1. **`fetch_history(ticker)`** (Yahoo 2y + Stooq history fallback) and **`signals.py`** — port
   Pine logic; validate against Data Window values before anything else.
2. **DB migration** in `db.py` — `alert_watch` (bucket-based) + `alert_log` tables; settings
   keys added to `DEFAULT_SETTINGS` (`ntfy_server`, `ntfy_topic`, `alert_enabled`,
   `alert_check_time`), stored via the existing `json.dumps` convention like all settings.
3. **`notify.py`** — ntfy POST helper (bucket+action title) + "send test".
4. **`alert_job.py`** — scheduler thread (ET-aware timer + on-boot catch-up) with bar-date
   dedupe; reuses sm_job pattern + single-flight lock.
5. **`routes/alerts.py`** — manage the two lists, move Buy↔Held, settings, log, check-now,
   test-push; auto-seed. Register blueprint at `/api/alerts`.
6. **`static/js/views/Alerts.js`** + route in `app.js` + nav entry between Research and Trades.
   Plus the **"★ Watch to Buy"** button in `Research.js`.
7. **Wire scheduler start** into `app.py` — guard against the dev reloader double-start
   (`WERKZEUG_RUN_MAIN` / only when not reloading). Docker runs `python app.py` single-process
   with `FLASK_DEBUG=0` (no reloader, no gunicorn workers) → exactly one scheduler thread, no
   duplicate-alert risk. The guard only matters for local dev.
8. **Verify** — unit-test the engine; send a real test push to the phone; simulate
   "resumed after downtime" to confirm exactly one alert per due signal and none on re-run.

---

## Data model (proposed)

```
alert_watch(
  id INTEGER PK, ticker TEXT UNIQUE,
  bucket TEXT,          -- BUY | HELD
  kind   TEXT,          -- Trade | Invest
  active INTEGER DEFAULT 1,
  created_at TEXT
)

alert_log(
  id INTEGER PK, ticker TEXT,
  bucket TEXT,          -- BUY | HELD (which list it was in when it fired)
  action TEXT,          -- BUY | ADD | SELL (what the signal wants)
  signal_dir TEXT,      -- BUY | SELL (raw engine direction; dedupe axis)
  kind TEXT,
  bar_date TEXT,        -- the daily bar the signal fired on (dedupe key)
  price REAL, message TEXT,
  sent_at TEXT, transport TEXT,
  ok INTEGER,           -- send succeeded
  error TEXT            -- fetch/send failure detail, so a dead ticker is diagnosable
)
```
**Dedupe:** only fire if the signal's bar date > the last logged `bar_date` for that
`(ticker, signal_dir)`. Because Held watches two directions, dedupe on `signal_dir` (not
bucket) so a BUY fire never suppresses a later SELL. Edge-trigger prevents re-firing across
consecutive bars; stored bar date prevents re-firing on restart.

**Fetch failures are logged** (`ok=0`, `error=...`), so a ticker silently failing to fetch for
days is visible instead of invisible.

Settings keys: `ntfy_server`, `ntfy_topic`, `alert_enabled`, `alert_check_time` — added to
`DEFAULT_SETTINGS`, JSON-encoded like the rest.

---

## Open decisions (defaults are fine unless changed)
- **RSI trend bars**: Pine default is 2 (two consecutive up-bars). Keep as default, possibly
  expose per-alert later.
- **Alert timing**: fire once shortly after 4pm ET close, or evaluate hourly after close
  (redundant but robust). ET-based bar-date dedupe makes either safe.
- **ntfy hosting**: start on `ntfy.sh` (long random topic); self-host container later.
- **Reverse move**: a "Back to Buy" on Held rows is trivial if wanted; not needed for v1.

---

## Limitations to flag in the build
- Yahoo is unofficial (rate-limit/format risk) → Stooq history fallback, one call/ticker/run,
  cache. `fetch_history` is net-new code (the existing `fetch_price` is single-quote only).
- Indicators need long warmup history (~2y) to match TradingView; do not evaluate on 3mo.
- Daily-close only, not intraday.
- Public ntfy.sh topic is readable by anyone with the topic name → long random topic or
  self-host.
