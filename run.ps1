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

    # Re-run whenever requirements.txt itself changes, not just once ever
    # (a stale marker used to let new dependencies go uninstalled forever).
    $needInstall = $true
    if (Test-Path ".venv\.pip-installed") {
        $cached = Get-FileHash ".venv\.pip-installed" -Algorithm SHA256
        $current = Get-FileHash "requirements.txt" -Algorithm SHA256
        if ($cached.Hash -eq $current.Hash) { $needInstall = $false }
    }
    if ($needInstall) {
        Write-Host "Installing dependencies..." -ForegroundColor Yellow
        pip install -q -r requirements.txt
        Copy-Item "requirements.txt" ".venv\.pip-installed" -Force
        Write-Host "✓ Dependencies installed" -ForegroundColor Green
    } else {
        Write-Host "Using cached dependencies..." -ForegroundColor Cyan
    }

    # Playwright's Chromium is used for the CRM login check (DOM-based)
    if (-not (Test-Path ".venv\.playwright-installed")) {
        Write-Host "Installing Chromium for CRM checks (one-time, ~115 MB)..." -ForegroundColor Yellow
        python -m playwright install chromium
        New-Item -Path ".venv\.playwright-installed" -ItemType File -Force | Out-Null
        Write-Host "✓ Chromium installed" -ForegroundColor Green
    } else {
        Write-Host "Using cached Chromium..." -ForegroundColor Cyan
    }

    Write-Host "Starting case-wizard..." -ForegroundColor Yellow
    python app/launch.py
}
catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
