@echo off
setlocal enabledelayedexpansion
REM case-wizard: Desktop app launcher

cd /d "%~dp0"

echo Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install from https://python.org
    pause
    exit /b 1
)

REM Create venv if missing
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment
        pause
        exit /b 1
    )
)

REM Activate venv
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment
    pause
    exit /b 1
)

REM Check if we need to install (first time or requirements.txt changed)
if not exist ".venv\.pip-installed" (
    echo Installing dependencies (first run)...
    pip install -q -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Failed to install dependencies
        pause
        exit /b 1
    )
    echo. > .venv\.pip-installed
) else (
    echo Using cached dependencies...
)

echo Starting case-wizard...
python -m streamlit run app/main.py
if errorlevel 1 (
    echo ERROR: Streamlit failed to start
    pause
    exit /b 1
)

pause
