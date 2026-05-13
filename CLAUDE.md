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

## Current State

- ✅ All core endpoints working (market check, research, trades, valuation, smart money)
- ✅ Vue.js frontend with responsive design (Mac desktop + iPhone via Tailscale)
- ✅ Valuation calculator with correct equity multiplier formula, payout as %, MOS logic
- ✅ Smart money integration (queries 118 gurus, 13F holdings)
- ✅ Mobile layout fixed (topbar scrolls, tables don't overflow)
- ✅ **Docker deployment** — one-command install (`install.sh` / `Install-Horizon.ps1`), auto-restart on crash/reboot
- ✅ **Data backup/restore** — Settings tab → Export/Import JSON (full round-trip tested)
- ✅ **Background smart money refresh** — Smart Money tab → "Update Data (SEC 13F)" button, streams progress, auto-refresh on done

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

## Maintenance Notes

- SEC identity: set via `SEC_IDENTITY` env var (or on first ETL run, the CLI prompts and saves to `~/.smart_money/settings.json`)
- Valuation formula: Equity Multiplier = (r/req)² + (d/req)×(1+r/req) where r=reinvested%, d=distributed%, req=required_return%
- Payout inputs: Accept percentages (27, not 0.27); frontend converts ÷100 before API
- MOS: Applies 10% discount to ROE only; payout stays at median
