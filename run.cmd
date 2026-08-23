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

REM Install dependencies
echo [4/5] Checking dependencies...
if not exist ".venv\.pip-installed" (
    echo Installing from requirements.txt...
    pip install -q -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Failed to install dependencies
        echo Try: pip install -r requirements.txt
        pause
        exit /b 1
    )
    echo. > .venv\.pip-installed
    echo Dependencies installed
) else (
    echo Using cached dependencies
)

REM Launch app
echo [5/5] Starting case-wizard...
echo.
python -m streamlit run app/main.py
if errorlevel 1 (
    echo.
    echo ERROR: Streamlit failed to start
    echo.
    pause
    exit /b 1
)

echo.
pause
