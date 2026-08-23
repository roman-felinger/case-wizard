#!/usr/bin/env powershell
$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

try {
    Write-Host "Checking Python..." -ForegroundColor Yellow
    $python = Get-Command python -ErrorAction Stop
    Write-Host "✓ Python found" -ForegroundColor Green

    if (-not (Test-Path ".venv")) {
        Write-Host "Creating virtual environment..." -ForegroundColor Yellow
        python -m venv .venv
        Write-Host "✓ Virtual environment created" -ForegroundColor Green
    }

    Write-Host "Activating virtual environment..." -ForegroundColor Yellow
    .\.venv\Scripts\Activate.ps1

    # Only install if first run (marker file doesn't exist)
    if (-not (Test-Path ".venv\.pip-installed")) {
        Write-Host "Installing dependencies (first run)..." -ForegroundColor Yellow
        pip install -q -r requirements.txt
        New-Item -Path ".venv\.pip-installed" -ItemType File -Force | Out-Null
        Write-Host "✓ Dependencies installed" -ForegroundColor Green
    } else {
        Write-Host "Using cached dependencies..." -ForegroundColor Cyan
    }

    Write-Host "Starting case-wizard..." -ForegroundColor Yellow
    python -m streamlit run app/main.py
}
catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
