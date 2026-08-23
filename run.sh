#!/bin/bash
# case-wizard: Start the desktop app
# Works on macOS and Linux

set -e

cd "$(dirname "$0")"

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  Starting case-wizard Desktop App                              ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found! Install from https://python.org"
    exit 1
fi

echo "✓ Python: $(python3 --version)"

# Create/activate venv
echo ""
echo "Setting up environment..."
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -q -r app/requirements.txt

echo ""
echo "✅ Ready!"
echo ""
echo "Starting app..."
echo "Browser will open automatically at http://localhost:8501"
echo "Close the terminal to exit the app."
echo ""

# Run Streamlit app
streamlit run app/main.py
