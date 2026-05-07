# Horizon — Investment Research & Trading Dashboard

Local web app for consolidated research, valuation, trading, and smart money tracking. Access from Mac or iPhone via Tailscale.

## Quick Start

```bash
cd /Users/drewpfitzner/Documents/Projects/Claude_Projects/Horizon
source venv/bin/activate
python app.py
```

Then open http://localhost:5000 in your browser.

**Via Tailscale**: Once running, access from iPhone via your Tailscale IP (e.g., http://100.xx.x.xx:5000).

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

## Maintenance Notes

- SEC identity: `drew.pfitzner@gmail.com`
- Valuation formula: Equity Multiplier = (r/req)² + (d/req)×(1+r/req) where r=reinvested%, d=distributed%, req=required_return%
- Payout inputs: Accept percentages (27, not 0.27); frontend converts ÷100 before API
- MOS: Applies 10% discount to ROE only; payout stays at median
