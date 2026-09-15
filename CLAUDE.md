# Horizon — Investment Research & Trading Dashboard

Local web app for consolidated research, valuation, trading, and smart money tracking. Access from Mac or iPhone via Tailscale.

## Quick Start

**Local development (Mac/Linux):**
```bash
cd Horizon
source venv/bin/activate
python app.py
# Open http://localhost:5001
```

**Docker (Mac/Linux/Windows):**
```bash
cd Horizon
bash install.sh          # First time: builds image, starts container
# Open http://localhost:5001
bash update.sh           # After code changes: rebuild + restart
```

**Windows Docker:**
```powershell
cd Horizon
.\Install-Horizon.ps1    # First time
.\Update-Horizon.ps1     # After updates
```

**Via Tailscale**: Once running, access from any device via your Tailscale IP (e.g., http://100.xx.x.xx:5001).

---

## Your Workflow

1. **Market Check** (daily) — 6 indicators (Fed, VIX, RSI, Stochastic, S5FI, Fear/Greed) → outputs CAN TRADE? + position size %. **Fetch live data** fills all six from public sources; optional auto-fill does it on a schedule (see *Live market data*).
2. **Research** (as needed) — Checklist (fundamentals + technicals) → Valuation → Smart money lookup → Decision (TRADE/INVEST/NO ACTION)
3. **Trades** (when it happens) — Log entries/exits → System auto-calculates ROI, win/loss, performance
4. **Smart Money** (reference) — Search by ticker (who holds it, %) or guru (full portfolio)

---

## Tech Stack

- **Backend**: Flask (Python)
- **Frontend**: Vue.js (reactive forms, live calculations)
- **Databases**: 
  - `horizon.db` — your journal, research, trades, valuations
  - `smart_money.db` (imported) — guru holdings from SEC 13F filings
- **Deployment**: Local only (Tailscale for mobile access)

---

## Architecture

**Endpoints** (all in `routes/`)
- `/api/market-check` — Daily market gate input/output
- `/api/research` — Research checklist, valuation, smart money lookups
- `/api/trades` — Trade logging, performance tracking
- `/api/trades/import` — CSV preview/apply for the broker import
- `/api/smart-money` — Guru + ticker search (queries smart_money.db), 13F update + weekly schedule
- `/api/market-data` — Live indicator snapshot, S5FI rebuild, market-check auto-fill schedule
- `/api/valuation` — Equity multiple calculator (inputs: 5yr ROE, payout ratio, equity, shares; outputs: valuation + discount %)

**Components** (Vue.js in `static/js/views/`)
- Home, Market Check, Research, Watchlist, Trades, Smart Money, Settings
- Each has forms + real-time preview; results stored to horizon.db

**Database** (`db.py`)
- Schema: market_check, researched_stocks, valuations, trades, trade_fills (the
  broker-fill ledger the CSV import derives positions from), trade_imports
- All via SQLite; no external dependencies

---

## Key Features

### Market Check
- 6 indicators once per day → get YES/NO to trade + position size %
- **Fetch live data** button fills all six; or turn on the daily auto-fill in Settings
- Persists for the day; update if changed
- Notes field for context

### Research
- Checklist template (fundamentals + technicals)
- **Valuation calculator**: Enter 5yr ROE, payout ratio (%), required return → get valuation, equity multiplier, over/undervalued %
  - Uses equity multiple method (no discounted cash flow)
  - MOS (10% margin of safety) for conservative valuation
  - Shows average/median/MOS across 5 years
- Smart money lookup (which gurus hold, %, QoQ changes)
- Decision: TRADE / INVEST / NO ACTION
- Can mark for watchlist

### Trades
- Log entry (ticker, date, price, shares)
- Log exit → auto-calculates ROI, P&L, win/loss
- View historical trades + monthly performance
- **Import** tab: paste an IBKR CSV and the log updates itself (see *Importing
  from the broker* below)

### Smart Money
- Search by ticker → see all gurus holding, weights, QoQ changes
- Search by guru name → see full portfolio (47 holdings)
- Top holdings across all gurus
- Color-coded: green=new/increased, red=decreased/exited, yellow=5%+ weight

---

## Design Principles

- **Research is async** — research stocks anytime; only *trade* when market gate = YES
- **Smart money is validation, not a gate** — can trade stocks with no guru holdings
- **No external APIs** — no keys, no accounts, no paid feeds. The indicator fetch uses only public endpoints (FRED, Yahoo, CNN); everything else is local.
- **Tailscale for privacy** — no public internet exposure

---

## Development Workflow

**Quick iteration (local venv):**
```bash
source venv/bin/activate
python app.py
# Edit code → browser refresh (auto-reload on debug=True)
# Static assets (.js/.css) reload instantly
```

**Production (Docker):**
```bash
git add . && git commit -m "msg"
bash update.sh           # Rebuilds image, restarts container, ./data/ preserved
# Or on Windows: .\Update-Horizon.ps1
```

**Inspect container:**
```bash
docker compose logs -f          # Stream logs
docker compose exec horizon bash # Shell into running container
docker compose down             # Stop
```

**Share with others:** Push to repo, they run `install.sh` or `Install-Horizon.ps1` on their machine.

## Implementation Notes

- **Background jobs:** `sm_job.py` spawns `python cli.py update` in a thread inside `smart_money/`, streams stdout to a ring buffer (max 200 lines), exposed via `/api/smart-money/update/status`
- **Vendored smart_money:** The smart_money ETL package lives at `Horizon/smart_money/` (vendored, not a sibling repo). Its `smart_money/config.py` honors `SMART_MONEY_DB_PATH` / `SMART_MONEY_DATA_DIR` env vars so the ETL writes to the same DB Flask reads from
- **Data paths:** All DB/config paths accept env vars (`HORIZON_DB_PATH`, `SMART_MONEY_DB_PATH`, `SMART_MONEY_DIR`) for flexibility between dev/Docker
- **Docker context:** Build context is `Horizon/` itself; single `requirements.txt` installs both Horizon and smart_money deps
- **Flask debug:** Set `FLASK_DEBUG=0` in Docker so auto-reloader doesn't kill background threads; defaults to `1` (true) locally
- **Schedulers:** three daemon threads, all started in `app.py` behind the `WERKZEUG_RUN_MAIN` guard so the dev reloader doesn't double them — `alert_job` (daily signal check), `sm_job` (weekly 13F update), `market_data_job` (daily market-check fill). Each wakes at most hourly so a settings change lands without waiting out the full interval, and each catches up on boot if the box was off through its slot
- **Alerts dedupe:** each watch carries a `last_checked_bar` watermark; a ticker with a NULL watermark is *armed* at the current bar and fires nothing (no stale back-fill). Removing a watch is therefore a **soft delete** (`active = 0`) — a hard delete dropped the watermark, so remove/re-add re-armed the ticker and swallowed the signal in progress. Re-adding revives the same row.
- **Alerts "Signal now"** (`GET /api/alerts/now` → `alert_job.current_state()`): read-only snapshot of every active watch at the latest closed bar, ignoring the watermark and sending nothing. Reports the edge on that bar plus the most recent signal in the 2y window, tagged `sent` / `missed` (watermark was already past it) / `pending`. Use it when an expected alert never arrived — a normal check can't tell you, since an armed or already-fired ticker is silent by design. Network-bound (parallel price fetches), so it's an explicit button, not on mount.

## Maintenance Notes

- SEC identity: set via `SEC_IDENTITY` env var (or on first ETL run, the CLI prompts and saves to `~/.smart_money/settings.json`)
- Valuation formula: Equity Multiplier = (r/req)² + (d/req)×(1+r/req) where r=reinvested%, d=distributed%, req=required_return%
- Payout inputs: Accept percentages (27, not 0.27); frontend converts ÷100 before API
- MOS: Applies 10% discount to ROE only; payout stays at median

## Importing from the broker (`ibkr_import.py`, `routes/trade_import.py`)

Trades → **Import**: paste an IBKR CSV, look at what it would change, apply it.
Nothing is written until you press Apply, and every row is shown with its
before → after before you do.

**The shape problem.** `trades` is one row per *position* — a single entry price,
a single share count, one optional exit. IBKR's CSV is one row per *fill*: a $100
DECK order comes back as two lines at different prices, and a position you scale
into over three weeks is six lines. So rows can't map to rows.

**The fix is a fills ledger.** `trade_fills` records every fill the importer has
ever seen, fingerprinted and linked to its trade row. A position row is then
*derived* from its fills — weighted-average entry, summed commission,
weighted-average exit — and re-derived from scratch whenever new fills land.
That gives:

- **Idempotence.** A fill whose fingerprint is already in the ledger contributes
  nothing. Re-pasting last month's file is a no-op; pasting a 1-month file and
  then an all-time file only moves what's genuinely new.
- **Order independence.** Derivation is sums and weighted averages over the
  *union* of ledger and file, so importing an older window after a newer one
  lands on the same numbers as the other order.
- **Scale-ins and sell-outs.** Adding to a live position is just more buy fills
  (entry price becomes the weighted average); selling out flattens it and closes
  the row.

**The fingerprint** is the broker's own `TransactionID`/`TradeID` when the file
has one, otherwise `ticker|date|side|qty|price` plus an occurrence counter so two
identical fills in one order stay distinct. A Flex Query is therefore the most
reliable input — see below.

**Hand-logged rows are folded in, not duplicated.** A row with no fills of its
own gets a synthetic *baseline* fill built from what it already says, so a CSV
holding only the sell can close a position you typed in by hand. If the file
plainly contains the fills that row was typed from (same quantity, same date),
the baseline is dropped and the row is *adopted* instead — corrected in place with
the broker's real price and commission rather than logged twice.

**What it ignores**: forex legs, dividends, adjustments, withholding, anything
that isn't a Buy or a Sell. Dividends are surfaced as a notice, since one on a
ticker with no position on file usually means you hold it outside Horizon.

**Commission** comes from the CSV per fill, so imported trades carry IBKR's
actual charge rather than the `commission_pct` estimate the hand-entry form
falls back to.

**It asks rather than guesses.** Three cases stop for a decision and block Apply
until answered:

| Question | When | Choices |
|---|---|---|
| `orphan_sell` | a sale whose buy predates the file, with no matching open position | supply the entry date + price, or leave it out |
| `oversold` | more sold than the window shows bought | log what's there, or skip and paste a longer file |
| `partial_exit` | sold down but not out | **split** (a closed row for the shares sold, keeping the realised P/L, plus an open row for the rest — entry commission apportioned) or **reduce** (one smaller open row, realised P/L not logged) |

A "leave it out" answer is recorded in the ledger under `source='ignored'`, so the
same sale doesn't raise the same question every month.

**Which report to export.** The Transaction History report works and is what the
feature was built against. A **Trades Flex Query** (Performance & Reports → Flex
Queries → Activity, CSV) is better and also supported: it carries `TradeID`,
which makes the dedupe exact rather than fingerprint-based, plus
`openCloseIndicator` and `fifoPnlRealized`. Add the **Open Positions** section and
a wide date range ("Last 365 days") and most of the ambiguity above disappears,
because the file itself says what you were holding before the window opened.
Activity Statement exports parse too — the parser matches columns by alias, not
position, so the three layouts all land in the same place.

**If an import gets a position wrong**, delete the row in the trade log and paste
the file again. Deleting cascades the row's fills out of the ledger, so the next
import sees them as new and rebuilds the position from scratch. Editing a row by
hand also works, but the next CSV that touches that position will re-derive the
columns the importer owns (entry/exit dates, prices, share count, fees) — notes,
strategy and sector are never overwritten.

**Tests**: `venv/bin/python -m unittest discover -s tests -t .` — 19 cases
covering re-imports, overlapping windows, both import orders, scale-ins,
sell-outs, partial exits in both shapes, adoption of hand-logged rows,
delete-and-rebuild, and each question.

## Live market data (`market_data.py`)

Fetches all six Market Check indicators, so none of them have to be copied off a
screen. Free public endpoints only — no API keys, no accounts.

| Indicator | Source | Notes |
|---|---|---|
| St. Louis Fed (STLFSI4) | FRED CSV download | weekly series, so the latest value is normally Friday-dated and a few days old |
| VIX | Yahoo `^VIX` | last *completed* daily bar |
| RSI | computed from `^GSPC` | `signals.compute_indicators`, same engine as the alerts |
| Stochastic | computed from `^GSPC` | reports **%D** (the line the gate thresholds describe); %K rides along in the response |
| S5FI | computed from the 500 constituents | see below |
| Fear & Greed | CNN `production.dataviz.cnn.io` | needs browser-ish headers (UA + `Referer`/`Origin`), else CNN answers "I'm a teapot. You're a bot." |

**RSI / Stochastic are computed, not scraped.** `signals.py` is already a faithful
port of the TradingView indicators, so feeding it `^GSPC` bars reproduces the chart's
Data Window exactly — verified against a live chart: close 7656.98, RSI 50.00,
%K 40.18, %D 20.65, all matching to 2dp.

**S5FI is rebuilt from the index.** TradingView's `INDEX:S5FI` is licensed and has no
free feed, so we recompute it: S&P 500 constituent list from Wikipedia (cached a week,
falls back to the last good cache if the markup changes), then 6 months of daily closes
per member via Yahoo's multi-symbol `spark` endpoint, counting how many closed above
their own 50-day SMA. Verified at 38.77 against TradingView's 38.76 on the same bar —
the 0.01 is the 503-listed-tickers vs 500-index-members difference.

Constraints learned the hard way:
- `spark` accepts at most **20 symbols per call** — 25+ returns HTTP 400.
- Firing the ~26 batches back-to-back trips a Yahoo **429 cooldown** that then blocks
  *every* Yahoo endpoint for a couple of minutes. `SPARK_PAUSE` (1.5s) plus the
  escalating retry backoff keeps it under the limit. A full rebuild takes ~1–2 minutes.
- Because it's slow, S5FI never runs inline in a request: `market_data.snapshot()`
  returns the cached value with a `stale` flag, and `market_data_job` recomputes it in
  a background thread (`POST /api/market-data/s5fi/refresh`, poll `/s5fi/status`).
- FRED times out serving the full series; the fetch asks for a 180-day window.

**Auto-fill** (`market_data_job.auto_fill`): fetches all six and upserts the day's
`market_check` row via the shared `routes.market_check.upsert_values`, so scheduled
and hand-entered rows are identical. It refuses to save a partial set (any indicator
that failed → nothing written, the reason is in the job log), and `notes_if_new`
means an automated fill never overwrites a note you typed. Off by default; enable
with a time in Settings → Market Check Auto-Fill. Rows are dated by the **US market
date** at run time, matching the session the numbers describe.

## Smart Money weekly auto-update (`sm_job.start_scheduler`)

Runs the same `cli.py update` the button runs, once a week (default Sunday 07:00 ET),
configurable in Settings → Smart Money Auto-Update. Weekly is the right cadence: 13Fs
land in bursts around the 45-day post-quarter deadline, so most runs are no-ops and
nothing is ever more than a week stale.

- **Boot catch-up:** if the slot passed while the machine was off, the run happens at
  next startup (`_due()` compares `sm_last_auto_run` against the most recently passed slot).
- **Switching it on stamps a baseline** rather than firing immediately — with no
  recorded run, every past slot would look "missed" and enabling it would kick off a
  full SEC pull on the next restart. The manual button is there for an immediate run.
- A scheduled run that collides with a manual one simply skips; next week catches it.

## Terminal research script (`research_cli.py`)

Standalone stdlib CLI (no Flask/deps) that reproduces the Research view from SEC EDGAR, for sanity-checking a ticker before finviz/TradingView. `python3 research_cli.py GOOG AAPL [--price N] [--required N] [--json]`.

Pulls XBRL company facts → 10-item Fundamentals checklist + score, SM holding (from local `smart_money.db`), and the equity-multiple valuation using the exact `routes/valuation.py` formula. Price from Yahoo chart API (Stooq fallback). Prints CAN TRADE / CAN INVEST / NO ACTION / VETOED / SKIP.

**Method details:**
- **ROE uses average equity** ((prior+current)/2), matching finviz/the app — not ending equity.
- **Shares = Yahoo `impliedSharesOutstanding`** (all classes) so dual-class names (GOOG/BRK/V) get the correct total. companyfacts only exposes undimensioned facts, so multi-class SEC share/EPS counts are stale/partial; Yahoo is the authoritative total. See memory `dual-class-shares-valuation`.
- **EPS growth** uses reported diluted EPS; falls back to net-income/diluted-shares, then net-income growth (tagged `(NI/sh)`/`(NI)`) for filers like VISA that report EPS only by share class.
- **EPS Growth Next Yr** is a forward analyst estimate from Yahoo `earningsTrend` (undocumented, crumb-auth, uneven coverage) — shown with `~` marker, **not scored, not in the trade gate**.

**Vetoes / skips (equity-multiple doesn't apply):**
- **Negative book equity** → VETOED.
- **Median ROE > 50%** → VETOED (buybacks shrink equity to a sliver, exploding the multiplier into nonsense, e.g. AAPL/NVDA/HD). Blunt cutoff: borderline names just under it (KO ~43%, V ~46%, NFLX ~38%) still produce shaky valuations — treat high-ROE-but-passing valuations with caution.
- **Financial sector (SIC 6000–6799: banks/insurers/brokers/REITs)** → SKIP. The equity-multiple model needs a dedicated bank valuation method. **Avoid trading financials via this tool until that method is defined** (user to provide). Detected by SIC from SEC submissions; software-for-banks (e.g. JKHY, SIC 7372) is correctly *not* flagged.

**Unsupported:** IFRS / foreign 20-F filers (e.g. SAP) report under `ifrs-full`, not `us-gaap` — returns a clear "not supported" message. Foreign filers that file 10-K in us-gaap (CHKP, ACN, GRMN) work fine.

**App integration (Prefill):** `research_cli.py` is also the shared engine behind the app's Prefill. `analyze()` returns a rich dict; `to_horizon_prefill()` maps it to Horizon form fields (checklist flags keyed by DB column name + `roe1..5`/`payout1..5` latest-first with payout as %). `routes/prefill.py` exposes `GET /api/prefill/<ticker>`. The **Prefill** button in the Research view fills the fundamentals checklist + Price<MOS (leaves technicals/notes/decision alone); the one in the Valuation view fills ROE/payout/equity/shares/price. Both show a banner with verdict + financial/veto warnings. Network-bound (SEC + Yahoo), so it's an explicit button click, not on-blur. Payout is emitted as % (form divides by 100 before the API), and non-dividend years are 0 (not omitted) so the 5-yr median isn't skewed.

## Pine Script (`horizon_signal.pine`)

TradingView indicator that mirrors the Research view's Technicals checklist. Edge-triggered: fires on the first bar all conditions go true simultaneously.

**Buy gates** (all must be true): RSI < 35 (Trade) or < 40 (Invest); RSI rising for N bars (`rsiTrendBars`, 0=off, 1=1 up-bar, 2+=N consecutive); Stoch %D < 20; %K > %D; volume > 10-bar MA (optional).

**Sell gates**: RSI > 55 (Trade) or > 60 (Invest); Stoch %D > 80; %K < %D.

**Stochastic defaults**: 14 / 1 / 3 (length / %K smoothing / %D) — matches TradingView's built-in Stoch so the chart's blue/orange lines = our internal `k`/`d`. Using %K smoothing > 1 causes a lag where smoothed %K stays below smoothed %D on the first up-bar off a bottom, suppressing buys after sharp drops.

**Volume filter caveat**: A single huge spike (e.g. earnings) pulls the 10-bar MA up and can block buy signals on subsequent normal-volume recovery bars. Lengthen `volMaLen` or disable the filter when this matters.
