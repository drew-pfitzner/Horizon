# Pull latest code, rebuild, and restart Horizon. Data in .\data is preserved.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Pulling latest changes..."
git pull --ff-only

Write-Host "Rebuilding Horizon image..."
docker compose build

Write-Host "Restarting Horizon..."
docker compose up -d

Write-Host ""
Write-Host "Update complete. Horizon at http://localhost:5001" -ForegroundColor Green
