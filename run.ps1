#!/usr/bin/env powershell
# case-wizard: Desktop app launcher
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Write-Host "ERROR: Python not found" -ForegroundColor Red; exit 1 }
if (-not (Test-Path ".venv")) { python -m venv .venv }
.\.venv\Scripts\Activate.ps1
pip install -q -r requirements.txt
streamlit run app/main.py
