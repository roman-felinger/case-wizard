@echo off
REM case-wizard: Desktop app launcher
REM Just double-click to run!

cd /d "%~dp0"

python --version >nul 2>&1 || (
    echo ERROR: Python not found. Install from https://python.org
    pause & exit /b 1
)

if not exist ".venv" python -m venv .venv
call .venv\Scripts\activate.bat

pip install -q -r requirements.txt
streamlit run app/main.py
