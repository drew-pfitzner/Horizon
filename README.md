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

**Windows (Batch):**
```cmd
git clone <repo-url> Horizon
cd Horizon
install.bat
```

*Alternative (PowerShell):*
```powershell
.\Install-Horizon.ps1
```

Open <http://localhost:5001>.

## Update

For Docker rebuilds (e.g., after Dockerfile changes):
```bash
bash update.sh    # Mac / Linux
update.bat        # Windows
```

For code-only updates: **Settings → App Updates → Update & Restart** (no script needed; pulls latest, restarts in-place).

Data in `./data/` is preserved across rebuilds.

## First-time setup inside the app

1. Open **Smart Money → Update Data (SEC 13F)** to populate guru holdings (one-time, ~minutes).
2. Run **Market Check** daily; do **Research**, log **Trades** as you go.
3. Use **Settings → Data Backup** to export Horizon data and the smart money DB before machine moves.

See `CLAUDE.md` for architecture and endpoint notes.
