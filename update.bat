@echo off
REM Pull latest code, rebuild, and restart Horizon. Data in .\data is preserved.

setlocal enabledelayedexpansion
pushd "%~dp0"

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
