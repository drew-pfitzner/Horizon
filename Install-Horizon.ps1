# Horizon installer (Windows PowerShell). Builds and starts Horizon in Docker.
# Requires: Docker Desktop for Windows (WSL2 backend).
# Run from this folder:   .\Install-Horizon.ps1
#  (If blocked: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass; .\Install-Horizon.ps1)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Write-Host "ERROR: Docker is not installed." -ForegroundColor Red
  Write-Host "Install Docker Desktop: https://www.docker.com/products/docker-desktop/"
  exit 1
}

try { docker compose version | Out-Null } catch {
  Write-Host "ERROR: 'docker compose' (v2) is not available." -ForegroundColor Red
  exit 1
}

New-Item -ItemType Directory -Force -Path .\data | Out-Null

Write-Host "Building Horizon image..."
docker compose build

Write-Host "Starting Horizon..."
docker compose up -d

Write-Host ""
Write-Host "Horizon is running at:  http://localhost:5001" -ForegroundColor Green
Write-Host "Via Tailscale:          http://<your-tailscale-ip>:5001"
Write-Host "Logs:                   docker compose logs -f"
Write-Host "Stop:                   docker compose down"
