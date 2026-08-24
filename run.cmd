@echo off
setlocal enabledelayedexpansion

REM case-wizard: Desktop app launcher
REM Debugging: Show this file is running
title case-wizard startup
cd /d "%~dp0"
echo.
echo === case-wizard launcher ===
echo Working directory: %CD%
echo.

REM Check Python
echo [1/5] Checking Python...
python --version
if errorlevel 1 (
    echo.
    echo ERROR: Python not found or not in PATH
    echo.
    echo Solution:
    echo 1. Install Python from https://python.org
    echo 2. During installation, CHECK "Add Python to PATH"
    echo 3. Restart this script
    echo.
    pause
    exit /b 1
)

REM Create venv if missing
echo [2/5] Checking virtual environment...
if not exist ".venv" (
    echo Creating .venv directory...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment
        pause
        exit /b 1
    )
    echo .venv created successfully
)

REM Activate venv
echo [3/5] Activating virtual environment...
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment
    pause
    exit /b 1
)

REM Install dependencies - re-run whenever requirements.txt itself
REM changes, not just once ever (a stale marker used to let new
REM dependencies silently go uninstalled forever).
echo [4/6] Checking dependencies...
set "NEED_INSTALL=1"
if exist ".venv\.pip-installed" (
    fc /b "requirements.txt" ".venv\.pip-installed" >nul 2>&1
    if not errorlevel 1 set "NEED_INSTALL=0"
)
if "%NEED_INSTALL%"=="1" (
    echo Installing from requirements.txt...
    pip install -q -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Failed to install dependencies
        echo Try: pip install -r requirements.txt
        pause
        exit /b 1
    )
    copy /y "requirements.txt" ".venv\.pip-installed" >nul
    echo Dependencies installed
) else (
    echo Using cached dependencies
)

REM Install Playwright's Chromium - used for the CRM login check
echo [5/6] Checking CRM browser...
if not exist ".venv\.playwright-installed" (
    echo Installing Chromium for CRM checks - one-time, about 115 MB...
    python -m playwright install chromium
    if errorlevel 1 (
        echo ERROR: Failed to install Chromium
        echo Try: python -m playwright install chromium
        pause
        exit /b 1
    )
    echo. > .venv\.playwright-installed
    echo Chromium installed
) else (
    echo Using cached Chromium
)

REM Launch app
echo [6/6] Starting case-wizard...
echo.
python app/launch.py
if errorlevel 1 (
    echo.
    echo ERROR: Streamlit failed to start
    echo.
    pause
    exit /b 1
)

REM Clean exit - this also happens when the app auto-shuts-down after
REM the last browser tab closes. No pause: just let the window close.
exit /b 0
