#!/bin/bash
# case-wizard: Desktop app launcher
set -e
cd "$(dirname "$0")"
command -v python3 &>/dev/null || { echo "ERROR: Python 3 not found"; exit 1; }
[ -d ".venv" ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
streamlit run app/main.py
