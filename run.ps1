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

    Write-Host "Installing dependencies..." -ForegroundColor Yellow
    pip install -r requirements.txt
    Write-Host "✓ Dependencies installed" -ForegroundColor Green

    Write-Host "Starting case-wizard..." -ForegroundColor Yellow
    python -m streamlit run app/main.py
}
catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
