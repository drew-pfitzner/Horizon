#!/usr/bin/env bash
# Horizon installer (Mac / Linux). Builds and starts Horizon in Docker.
# Requires: Docker Desktop or Docker Engine + compose v2.
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: Docker is not installed."
  echo "Install Docker Desktop: https://www.docker.com/products/docker-desktop/"
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: 'docker compose' (v2) not available."
  exit 1
fi

if [ ! -d "../smart_money" ]; then
  echo "ERROR: ../smart_money not found. Horizon expects the smart_money project"
  echo "as a sibling directory (../smart_money) so it can be bundled into the image."
  exit 1
fi

mkdir -p data

# Seed existing DBs into the volume mount if present and not yet copied.
if [ -f horizon.db ] && [ ! -f data/horizon.db ]; then
  echo "Copying existing horizon.db into ./data/"
  cp horizon.db data/horizon.db
fi
if [ -f ../smart_money/data/smart_money.db ] && [ ! -f data/smart_money.db ]; then
  echo "Copying existing smart_money.db into ./data/"
  cp ../smart_money/data/smart_money.db data/smart_money.db
fi

echo "Building Horizon image..."
docker compose build

echo "Starting Horizon..."
docker compose up -d

echo
echo "Horizon is running at:  http://localhost:5001"
echo "Via Tailscale:          http://<your-tailscale-ip>:5001"
echo "Logs:                   docker compose logs -f"
echo "Stop:                   docker compose down"
