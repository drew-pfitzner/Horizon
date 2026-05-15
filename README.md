# Horizon

A personal investment research, valuation, and trading dashboard. Track your daily market decisions, research stocks, log trades, and reference "smart money" (SEC 13F guru holdings) all in one place.

**Access:** From your Mac, PC, or iPhone via Tailscale on the same network. Local only — no cloud, no external APIs.

---

## Installation

### Prerequisites

**Windows:**
- Docker Desktop for Windows (https://www.docker.com/products/docker-desktop/)
- Git for Windows (https://git-scm.com/download/win)

**Mac / Linux:**
- Docker Desktop or Docker Engine + compose v2 (https://docs.docker.com/compose/install/)
- Git (usually already installed; `brew install git` on Mac)

### First-Time Setup

**Windows (recommended: use batch file):**
1. Open Command Prompt or PowerShell
2. Clone the repo: `git clone <repo-url> Horizon`
3. Enter the directory: `cd Horizon`
4. Run: `install.bat` (double-click, or type in terminal)
5. Wait for Docker to build (~1-2 min). You'll see "Horizon is running at: http://localhost:5001"
6. Open your browser to **http://localhost:5001**

**Mac / Linux:**
```bash
git clone <repo-url> Horizon
cd Horizon
bash install.sh
# Open http://localhost:5001
```

**Via Tailscale (iPhone, other devices on your network):**
1. Install Tailscale on your phone: https://tailscale.com/download
2. Sign in with your account (free tier)
3. In Tailscale admin console (https://login.tailscale.com/admin):
   - Enable **DNS → MagicDNS**
   - Go to **Machines**, click your computer, edit machine name → set to `horizon`
4. From your phone: open browser to **http://horizon:5001**

---

## What Horizon Does

### 1. **Market Check** (Daily Gate)
Every day, input 6 market indicators to decide if it's a good day to trade:
- Fed Funds Rate
- VIX (volatility)
- RSI, Stochastic (technical)
- S&P 500 % Above 50-Day MA (S5FI)
- Fear & Greed Index

The app scores each indicator (LOW/MED/HIGH) and tells you:
- **Can I trade today?** (YES / NO)
- **Position size if yes?** (1-2% of capital)

Results persist for the day; update if conditions change.

### 2. **Research**
Before you trade a stock, document your analysis:
- **Checklist**: Verify fundamentals (earnings, debt, growth) and technicals (trend, support/resistance)
- **Valuation**: Calculate fair value using the equity multiple method:
  - Input: 5-year ROE %, payout ratio %, required return %
  - Output: Fair value, over/undervalued %, margin of safety
- **Smart Money**: See which Wall Street gurus hold the stock and their latest holdings
- **Decision**: Mark as TRADE / INVEST / NO ACTION; optionally add to watchlist

### 3. **Trades**
Log entry and exit for each trade:
- Entry: ticker, date, price, shares
- Exit: exit date, exit price
- App auto-calculates: ROI %, P&L, win/loss
- View monthly performance and historical trade list

### 4. **Watchlist**
Stocks you marked as "watch" during research. Reference while doing market checks.

### 5. **Smart Money**
Search guru holdings:
- **By ticker**: See which gurus own it, % holdings, QoQ changes (green = new/increased, red = decreased)
- **By guru name**: See their full portfolio (47 holdings tracked)
- **Top holdings**: Across all 118 gurus

Based on SEC 13F filings (updated quarterly). Use for validation, not as a trade signal.

### 6. **Settings**
- **Pullback Thresholds**: Customize the RSI/Stochastic/S5FI/Fear&Greed cutoffs for your preferred position size
- **SEC Email**: Provide your SEC Edgar email for updating guru holdings (optional; one-time or quarterly)
- **Data Backup**: Export all your Horizon data (research, trades, valuations) as JSON; restore on a new machine
- **Smart Money Backup**: Export the guru holdings database (no need to re-run SEC update after restore)
- **App Updates**: Check for code updates and update + restart from within the app (no terminal needed)

---

## How to Use (Workflow)

### Daily

1. Open Horizon at http://localhost:5001 (or http://horizon:5001 on Tailscale)
2. Go to **Market Check**
3. Input today's 6 indicators
4. App tells you: "CAN TRADE? YES / NO · Position size: 1.5%"
5. If YES, you're cleared to research and trade

### As Needed

4. Find a stock you want to research
5. Go to **Research**
6. Fill out the checklist, valuation, smart money, and decision
7. If you decide to trade, go to **Trades**

### When You Trade

8. **Log Entry**: Ticker, date, price, # shares
9. **Later, Log Exit**: Exit date, exit price
10. App auto-calculates your ROI and P&L
11. View monthly performance in **Trades**

### References

- **Watchlist**: Stocks you're monitoring (no immediate action)
- **Smart Money**: Who holds this stock, what % allocation, any recent changes

---

## Updates

### Code Updates (from Settings tab)

Once installed, you can update without touching the terminal:

1. Open Horizon
2. Go to **Settings → App Updates**
3. Click **Check for Updates**
4. If updates available: click **Update & Restart**
5. Browser auto-reloads with new code

### Full Rebuild (dependencies or Docker changes)

If new Python dependencies or Dockerfile changes, run the installer script from your machine:

**Windows:**
```cmd
update.bat
```

**Mac / Linux:**
```bash
bash update.sh
```

Data in `./data/` is always preserved.

---

## Mobile Access

### iPhone / iPad

1. Install Tailscale on your phone
2. Sign in (same account as your computer)
3. Open browser to **http://horizon:5001**
4. Bookmark it for easy access
5. Works over cellular too

The app is mobile-optimized (responsive design). All tables, forms, and charts work on small screens.

---

## Data & Privacy

- **Local only**: Everything stays on your machine. No cloud, no external APIs (except SEC Edgar for guru data).
- **Databases**: 
  - `horizon.db` — your research, trades, valuations, settings
  - `smart_money.db` — guru holdings (SEC 13F filings)
- **Backup**: Export JSON at any time via Settings → Data Backup. Useful before machine moves.

---

## Troubleshooting

### App won't start after install

**Windows:**
- Make sure Docker Desktop is running (check system tray)
- Check that port 5001 is not already in use
- Run `update.bat` again to rebuild

**Mac / Linux:**
- Run `bash update.sh` to rebuild
- Check logs: `docker compose logs -f`

### "Uncommitted changes" in Settings → App Updates

This is usually a line-ending issue on Windows. Fix inside the container:
```cmd
docker compose exec horizon git config core.autocrlf true
```

Then refresh the page.

### Forgot to back up before upgrading?

If you just upgraded and lost data:
1. Stop the app: `docker compose down`
2. Restore from a previous backup file if you have one, or
3. Ask for help recovering the previous container image

### Smart Money data is old

Go to **Smart Money → Update Data (SEC 13F)** and click the button. It fetches the latest SEC filings and rebuilds the guru holdings database (~5-10 min). You only need to do this once, or periodically to stay current.

---

## For Developers

See `CLAUDE.md` for architecture, API endpoints, database schema, and deployment notes.

---

## Support

Questions or issues? Check the logs:
```bash
docker compose logs -f
```

Or refer to CLAUDE.md for the tech stack details.
