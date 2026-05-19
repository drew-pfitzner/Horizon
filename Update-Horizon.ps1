# Pull latest code, rebuild, and restart Horizon. Data in .\data is preserved.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Discard any local modifications to tracked files so git pull never blocks.
# (Install folder is treated as read-only; user data lives in .\data which is gitignored.)
git config core.autocrlf false 2>$null | Out-Null
$dirty = git status --porcelain
if ($dirty) {
  Write-Host "Discarding local changes to tracked files..."
  git reset --hard HEAD 2>$null | Out-Null
}

Write-Host "Pulling latest changes..."
git pull --ff-only

# Renormalize after pull in case .gitattributes changed.
git add --renormalize . 2>$null | Out-Null
git checkout -- . 2>$null | Out-Null

Write-Host "Rebuilding Horizon image..."
docker compose build

Write-Host "Restarting Horizon..."
docker compose up -d

Write-Host ""
Write-Host "Update complete. Horizon at http://localhost:5001" -ForegroundColor Green
