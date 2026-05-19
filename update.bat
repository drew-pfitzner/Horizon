@echo off
REM Pull latest code, rebuild, and restart Horizon. Data in .\data is preserved.

setlocal enabledelayedexpansion
pushd "%~dp0"

REM Fix Windows line-ending dirt that blocks git pull and in-app updates.
REM (Git for Windows defaults to autocrlf=true; this repo enforces LF via .gitattributes.)
git config core.autocrlf false >nul 2>nul
git diff --quiet >nul 2>nul
if errorlevel 1 (
  echo Resetting Windows line-ending changes...
  git checkout -- . >nul 2>nul
)

echo.
echo Pulling latest changes...
git pull --ff-only
if errorlevel 1 (
  color 0C
  echo ERROR: git pull failed.
  color 07
  pause
  exit /b 1
)

REM Renormalize after pull in case .gitattributes changed.
git add --renormalize . >nul 2>nul
git checkout -- . >nul 2>nul

echo.
echo Rebuilding Horizon image...
docker compose build
if errorlevel 1 (
  color 0C
  echo ERROR: Docker build failed.
  color 07
  pause
  exit /b 1
)

echo.
echo Restarting Horizon...
docker compose up -d
if errorlevel 1 (
  color 0C
  echo ERROR: Failed to restart Horizon.
  color 07
  pause
  exit /b 1
)

echo.
color 0A
echo Update complete. Horizon at http://localhost:5001
color 07
echo.
pause
