# Horizon

Local investment research, valuation, and trading dashboard with built-in SEC 13F smart money tracking. Runs in Docker; accessible on the local network (and via Tailscale).

## Install (one-click)

Prereq: Docker Desktop (or Docker Engine + compose v2).

**Mac / Linux:**
```bash
git clone <repo-url> Horizon
cd Horizon
bash install.sh
```

**Windows (PowerShell):**
```powershell
git clone <repo-url> Horizon
cd Horizon
.\Install-Horizon.ps1
```

Open <http://localhost:5001>.

## Update

```bash
bash update.sh           # Mac / Linux
.\Update-Horizon.ps1     # Windows
```

Data in `./data/` is preserved across rebuilds.

## First-time setup inside the app

1. Open **Smart Money → Update Data (SEC 13F)** to populate guru holdings (one-time, ~minutes).
2. Run **Market Check** daily; do **Research**, log **Trades** as you go.
3. Use **Settings → Data Backup** to export Horizon data and the smart money DB before machine moves.

See `CLAUDE.md` for architecture and endpoint notes.
