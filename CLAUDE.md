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

1. **Market Check** (daily) — Input 6 indicators (Fed, VIX, RSI, Stochastic, S5FI, Fear/Greed) → outputs CAN TRADE? + position size %
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
- `/api/smart-money` — Guru + ticker search (queries smart_money.db)
- `/api/valuation` — Equity multiple calculator (inputs: 5yr ROE, payout ratio, equity, shares; outputs: valuation + discount %)

**Components** (Vue.js in `static/js/views/`)
- Home, Market Check, Research, Watchlist, Trades, Smart Money, Settings
- Each has forms + real-time preview; results stored to horizon.db

**Database** (`db.py`)
- Schema: market_check, researched_stocks, valuations, trades
- All via SQLite; no external dependencies

---

## Key Features

### Market Check
- Input 6 indicators once per day → get YES/NO to trade + position size %
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

### Smart Money
- Search by ticker → see all gurus holding, weights, QoQ changes
- Search by guru name → see full portfolio (47 holdings)
- Top holdings across all gurus
- Color-coded: green=new/increased, red=decreased/exited, yellow=5%+ weight

---

## Design Principles

- **Research is async** — research stocks anytime; only *trade* when market gate = YES
- **Smart money is validation, not a gate** — can trade stocks with no guru holdings
- **No external APIs** — everything local (smart_money.db, your data)
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
- **Alerts dedupe:** each watch carries a `last_checked_bar` watermark; a ticker with a NULL watermark is *armed* at the current bar and fires nothing (no stale back-fill). Removing a watch is therefore a **soft delete** (`active = 0`) — a hard delete dropped the watermark, so remove/re-add re-armed the ticker and swallowed the signal in progress. Re-adding revives the same row.
- **Alerts "Signal now"** (`GET /api/alerts/now` → `alert_job.current_state()`): read-only snapshot of every active watch at the latest closed bar, ignoring the watermark and sending nothing. Reports the edge on that bar plus the most recent signal in the 2y window, tagged `sent` / `missed` (watermark was already past it) / `pending`. Use it when an expected alert never arrived — a normal check can't tell you, since an armed or already-fired ticker is silent by design. Network-bound (parallel price fetches), so it's an explicit button, not on mount.

## Maintenance Notes

- SEC identity: set via `SEC_IDENTITY` env var (or on first ETL run, the CLI prompts and saves to `~/.smart_money/settings.json`)
- Valuation formula: Equity Multiplier = (r/req)² + (d/req)×(1+r/req) where r=reinvested%, d=distributed%, req=required_return%
- Payout inputs: Accept percentages (27, not 0.27); frontend converts ÷100 before API
- MOS: Applies 10% discount to ROE only; payout stays at median

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
