@echo off
REM case-wizard: Start the desktop app
REM Works on Windows - just double-click this file

cd /d "%~dp0"

echo.
echo ╔════════════════════════════════════════════════════════════════╗
echo ║  Starting case-wizard Desktop App                              ║
echo ╚════════════════════════════════════════════════════════════════╝
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python not found! Install from https://python.org
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version') do set PYVER=%%i
echo ✓ %PYVER%

echo.
echo Setting up environment...
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo Installing dependencies...
pip install -q -r app/requirements.txt

echo.
echo ✅ Ready!
echo.
echo Starting app...
echo Browser will open automatically at http://localhost:8501
echo Close this window to exit the app.
echo.

streamlit run app/main.py

pause
