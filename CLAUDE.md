# Horizon

## Vision
A unified web application that consolidates your complete investment research, analysis, and trading workflow into a single locally-hosted dashboard. Replaces Obsidian (journal + research), Excel spreadsheets (valuation + trading diary), and the smart-money TUI into one seamless system. Access from Mac or iPhone via Tailscale.

## Your Workflow

### 1. Market Check (Daily)
- **Input**: 6 market indicators (St. Louis Fed, VIX, RSI, Stochastic, S5FI, Fear/Greed Index)
- **Output**: Can I trade today? YES/NO + Position size % (LOW 2%, MED 1.5%, HIGH 1%, max 5% per stock)
- **Notes**: Context to review later
- **Frequency**: Once per day, persists for the day

### 2. Research Pipeline (As Needed)
- Scan TradingView for interesting stocks
- For each candidate:
  1. **Checklist** (fundamentals: ROA, ROE, ROI, margins, growth, ratios; smart money; liquidity; technicals: RSI, Stochastic)
  2. **Valuation** (equity multiple method: 4-year P/E history → equity per share → % over/undervalued)
  3. **Smart Money** (which gurus hold it, %, QoQ changes)
  4. **Decision**: TRADE / INVEST / NO ACTION
- If approved: Add to watchlist (but don't trade yet—wait for market gate)

### 3. Trade Execution (When It Happens)
- When you enter or exit a trade: Log to diary
- System auto-calculates: ROI, win/loss, monthly performance
- Build historical record for review

---

## Architecture

**Databases**
- `horizon.db` (new SQLite) — All journal, research, trades, valuations
- `smart_money.db` (existing) — Guru holdings, 13F data, imported at startup

**Backend**
- Flask (Python)
- Endpoints: `/api/market-check`, `/api/research`, `/api/trades`, `/api/smart-money`, etc.

**Frontend**
- Vue.js + HTML/CSS
- Responsive for Mac (desktop) + iPhone (Tailscale)
- No external API calls (all local)

**Deployment**
- Run locally: `python app.py`
- Access via Tailscale from any device on your network

---

## Database Schema

### MARKET_CHECK
```
id, date, st_louis_fed, vix, rsi, stochastic, s5fi, fear_greed
can_trade (YES/NO), position_size_pct
notes
```

### RESEARCHED_STOCKS
```
id, ticker, date_researched
fundamentals_checklist (JSON: {roa, roe, roi, margins, growth, ratios})
technicals_checklist (JSON: {rsi, stochastic, trend})
liquidity_check (PASS/FAIL)
smart_money_holders (JSON: array of gurus + %)
decision (TRADE/INVEST/NO_ACTION)
in_watchlist (YES/NO)
notes
valuation_latest (FK to VALUATIONS.id)
created_date, updated_date
```

### VALUATIONS
```
id, ticker, valuation_date
current_stock_price
year0_pe, year1_pe, year2_pe, year3_pe
equity_per_share
equity_multiplier
dollar_overvalued_pct (average across years)
assessment (UNDERVALUED/FAIR/OVERVALUED)
created_date
```

### TRADES
```
id, ticker, entry_date, entry_price, shares
position_size_pct
exit_date, exit_price
p_l, roi_pct
win_loss (WIN/LOSS/HOLD)
notes
created_date
```

---

## UI Tabs

### Home Dashboard
- Today's market gate status: **CAN TRADE? YES/NO**
- Today's position size: **X%**
- Today's notes: *context*
- Quick stats: *researched stocks in watchlist, open trades, month ROI*

### Market Check Tab
- Input 6 indicators
- System outputs: Can trade? + Position size level
- Notes field
- Save once per day (updates current day if changed)

### Research Tab
- **New Research** button → Checklist template
  - Fundamentals checklist (10 items)
  - Technicals checklist (RSI, Stochastic, trend)
  - Liquidity check (PASS/FAIL)
  - Embedded Smart Money lookup (shows gurus holding, %)
  - Valuation button (opens calculator inline or separate page)
  - Decision: TRADE / INVEST / NO ACTION
  - Notes field
- **Researched Stocks** list (all past research)
  - Columns: Ticker, date, decision, in_watchlist, latest valuation
  - Edit/view each research entry

### Watchlist Tab
- All researched stocks approved for TRADE/INVEST
- Columns: Ticker, entry price (from research), current price, latest valuation, decision, top guru holding
- Status: Waiting for market gate to flip to YES (then can enter)
- Add to TradingView link (external)

### Trades Tab
- **Log Trade** button → Entry form (ticker, date, price, shares, position %)
- When exited: Log exit (date, price) → Auto-calculates P&L, ROI, win/loss
- **Trade Log**: All trades with performance metrics
- **Monthly View**: Calendar showing trades entered/exited, wins/losses by month
- Performance summary: Total ROI, win rate, avg trade duration

### Smart Money Tab
- **Search by Ticker**: Enter ticker → Shows all gurus holding, %, QoQ changes (color-coded: green=new/increased, red=decreased/exited)
- **Search by Guru**: Enter guru name → Shows full portfolio (47 holdings) sorted by weight
- **Top Holdings**: Most-held stocks across all gurus (guru count, avg weight)
- **Embedded in Research**: When researching a stock, smart money data shows inline

---

## Smart Money Integration

The smart_money.db is queried via Flask endpoints and embedded throughout:

1. **In Research Tab**: When researching AAPL, see which gurus hold it, %, and QoQ status—approval for smart money check
2. **In Watchlist Tab**: Shows top guru holding each watchlist stock
3. **Standalone Smart Money Tab**: Full guru/ticker search interface (replaces TUI)
4. **Cross-check**: When entering trades, can see if smart money aligns with your research

---

## Tech Stack

| Layer | Tech | Why |
|-------|------|-----|
| **Backend** | Flask (Python) | Familiar, lightweight, runs on Mac, existing smart_money.py integration |
| **Database** | SQLite | Same as smart_money, no external dependencies |
| **Frontend** | Vue.js + HTML/CSS | Reactive forms, live calculations, responsive design |
| **Data** | Markdown for notes (optional) | Portable, version-controllable (future enhancement) |
| **Deployment** | Local + Tailscale | `python app.py` on Mac, Tailscale VPN for iPhone access |

---

## Key Design Decisions

- **Research is async**: You research stocks whenever TradingView scans find them, but can only *trade* when market gate = YES
- **Smart money is not a gate**: It's a validation check, not a requirement (you can trade stocks with no guru holdings)
- **One database per concern**: horizon.db for your workflow, smart_money.db for holdings data (keep them separate for clarity)
- **No external APIs**: Everything is local (smart_money.db, your data)
- **Tailscale for mobile**: No public internet exposure, secure network access

---

## Current State
- **Horizon repo initialized** with folder structure for research materials uploaded
- **Research materials uploaded**: Obsidian vault (journal + RMD checklist), Excel workbooks (valuation + trading diary), smart_money DB
- **Architecture designed**: Workflow, database schema, UI tabs, smart money integration documented

## Next Steps
1. **Planning session**: Map out implementation (models, routes, components, phases)
2. **Phase 1 (MVP)**: Market check tab + research tab (checklist + valuation)
3. **Phase 2**: Watchlist + trades + smart money tab
4. **Phase 3**: Refinements, performance, polish
5. **Deployment**: Package as local-served web app, test on iPhone via Tailscale

---

## Notes
- User email (SEC identity): drew.pfitzner@gmail.com
- Market conditions are gated by: St. Louis Fed indicator + VIX (recession/crash check) → RSI + STO + S5FI + Fear/Greed (pullback/correction check)
- Position sizing: Uses max() of the 4 pullback indicators to determine level
- Workflow is Freedom Trader methodology (as per Obsidian template)
