#!/usr/bin/env bash
# Pull latest code, rebuild, and restart Horizon. Data in ./data is preserved.
set -euo pipefail
cd "$(dirname "$0")"

echo "Pulling latest changes..."
git pull --ff-only

echo "Rebuilding Horizon image..."
docker compose build

echo "Restarting Horizon..."
docker compose up -d

echo
echo "Update complete. Horizon at http://localhost:5001"
