#!/usr/bin/env powershell
<#
.SYNOPSIS
Start case-wizard desktop app

.DESCRIPTION
Installs dependencies and starts the Streamlit app.
No background servers, no web server management.
Just click this, and the app opens.
#>

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

Write-Host "`n╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  Starting case-wizard Desktop App                              ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════════════╝`n" -ForegroundColor Cyan

# Check Python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "❌ Python not found! Install from https://python.org" -ForegroundColor Red
    exit 1
}

Write-Host "✓ Python: $(python --version)" -ForegroundColor Green

# Create/activate venv
Write-Host "`nSetting up environment..." -ForegroundColor Yellow
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
}

.\.venv\Scripts\Activate.ps1

# Install dependencies
Write-Host "Installing dependencies..." -ForegroundColor Yellow
pip install -q -r app/requirements.txt

Write-Host "`n✅ Ready!`n" -ForegroundColor Green
Write-Host "Starting app..." -ForegroundColor Cyan
Write-Host "Browser will open automatically at http://localhost:8501" -ForegroundColor Cyan
Write-Host "Close the terminal to exit the app.`n" -ForegroundColor Yellow

# Run Streamlit app
streamlit run app/main.py
