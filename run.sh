#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "Checking Python..."
command -v python3 &>/dev/null || { echo "ERROR: Python 3 not found"; exit 1; }
echo "✓ Python found"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    echo "✓ Virtual environment created"
fi

echo "Activating virtual environment..."
source .venv/bin/activate

# Re-run whenever requirements.txt itself changes, not just once ever
# (a plain marker file lets new dependencies go uninstalled forever).
if [ ! -f ".venv/.pip-installed" ] || ! cmp -s requirements.txt .venv/.pip-installed; then
    echo "Installing dependencies..."
    pip install -q -r requirements.txt
    cp requirements.txt .venv/.pip-installed
    echo "✓ Dependencies installed"
else
    echo "Using cached dependencies..."
fi

# Playwright's Chromium is used for the CRM login check (DOM-based)
if [ ! -f ".venv/.playwright-installed" ]; then
    echo "Installing Chromium for CRM checks (one-time, ~115 MB)..."
    python -m playwright install chromium
    touch .venv/.playwright-installed
    echo "✓ Chromium installed"
else
    echo "Using cached Chromium..."
fi

echo "Starting case-wizard..."
python app/launch.py
