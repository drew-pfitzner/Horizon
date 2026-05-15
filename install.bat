@echo off
REM Horizon installer (Windows). Builds and starts Horizon in Docker.
REM Requires: Docker Desktop for Windows, Git for Windows
REM Run from this folder: install.bat

setlocal enabledelayedexpansion
pushd "%~dp0"

REM Check Docker
where docker >nul 2>nul
if errorlevel 1 (
  color 0C
  echo ERROR: Docker is not installed.
  echo Install Docker Desktop: https://www.docker.com/products/docker-desktop/
  color 07
  pause
  exit /b 1
)

REM Check docker compose v2
docker compose version >nul 2>nul
if errorlevel 1 (
  color 0C
  echo ERROR: 'docker compose' is not available.
  echo Make sure Docker Desktop is updated to v2 or newer.
  color 07
  pause
  exit /b 1
)

REM Check Git
where git >nul 2>nul
if errorlevel 1 (
  color 0C
  echo ERROR: Git is not installed.
  echo Install Git: https://git-scm.com/download/win
  color 07
  pause
  exit /b 1
)

REM Create data directory
if not exist "data" mkdir "data"

echo.
echo Building Horizon image...
docker compose build
if errorlevel 1 (
  color 0C
  echo ERROR: Docker build failed.
  color 07
  pause
  exit /b 1
)

echo.
echo Starting Horizon...
docker compose up -d
if errorlevel 1 (
  color 0C
  echo ERROR: Failed to start Horizon.
  color 07
  pause
  exit /b 1
)

echo.
color 0A
echo Horizon is running at:  http://localhost:5001
echo Via Tailscale:          http://horizon:5001
echo.
echo Logs:                   docker compose logs -f
echo Stop:                   docker compose down
color 07
echo.
pause
