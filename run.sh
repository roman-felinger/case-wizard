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

# Only install if first run (marker file doesn't exist)
if [ ! -f ".venv/.pip-installed" ]; then
    echo "Installing dependencies (first run)..."
    pip install -q -r requirements.txt
    touch .venv/.pip-installed
    echo "✓ Dependencies installed"
else
    echo "Using cached dependencies..."
fi

echo "Starting case-wizard..."
python -m streamlit run app/main.py
