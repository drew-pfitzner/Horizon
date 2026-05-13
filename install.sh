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

mkdir -p data

echo "Building Horizon image..."
docker compose build

echo "Starting Horizon..."
docker compose up -d

echo
echo "Horizon is running at:  http://localhost:5001"
echo "Via Tailscale:          http://<your-tailscale-ip>:5001"
echo "Logs:                   docker compose logs -f"
echo "Stop:                   docker compose down"
