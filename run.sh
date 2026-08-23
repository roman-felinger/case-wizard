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

echo "Installing dependencies..."
pip install -r requirements.txt
echo "✓ Dependencies installed"

echo "Starting case-wizard..."
python -m streamlit run app/main.py
