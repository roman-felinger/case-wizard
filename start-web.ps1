#!/usr/bin/env powershell
<#
.SYNOPSIS
Start the case-wizard web dashboard (Flask backend + React frontend)

.DESCRIPTION
Starts both the Flask backend and React frontend dev servers.
Opens the dashboard in your browser at http://localhost:3000

Prerequisites:
- Python 3.8+
- Node.js 16+ with npm
#>

Write-Host "`n╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  Starting case-wizard Web Dashboard                            ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════════════╝`n" -ForegroundColor Cyan

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# Check Python
Write-Host "Checking Python..." -ForegroundColor Yellow
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "❌ Python not found! Install from https://python.org" -ForegroundColor Red
    exit 1
}
Write-Host "✓ Python found: $(python --version)" -ForegroundColor Green

# Check Node.js
Write-Host "`nChecking Node.js..." -ForegroundColor Yellow
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    Write-Host "❌ Node.js not found! Install from https://nodejs.org" -ForegroundColor Red
    exit 1
}
Write-Host "✓ Node.js found: $(node --version)" -ForegroundColor Green

# Install backend dependencies
Write-Host "`nSetting up backend..." -ForegroundColor Yellow
Set-Location backend
if (-not (Test-Path ".venv")) {
    Write-Host "Creating Python virtual environment..."
    python -m venv .venv
}
.\.venv\Scripts\Activate.ps1
pip install -q -r requirements.txt 2>$null
Write-Host "✓ Backend dependencies installed" -ForegroundColor Green
Set-Location ..

# Install frontend dependencies
Write-Host "`nSetting up frontend..." -ForegroundColor Yellow
Set-Location frontend
if (-not (Test-Path "node_modules")) {
    Write-Host "Installing npm dependencies... (this may take a minute)"
    npm install -q
}
Write-Host "✓ Frontend dependencies ready" -ForegroundColor Green
Set-Location ..

# Start servers in parallel
Write-Host "`n" -ForegroundColor Green
Write-Host "╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║  Starting services...                                          ║" -ForegroundColor Green
Write-Host "╚════════════════════════════════════════════════════════════════╝" -ForegroundColor Green

# Start backend
Write-Host "`n📡 Starting Flask backend on http://localhost:5000" -ForegroundColor Cyan
$backendProcess = Start-Process `
    -FilePath "python" `
    -ArgumentList "backend/app.py" `
    -WorkingDirectory $scriptDir `
    -PassThru `
    -NoNewWindow

# Start frontend
Write-Host "⚛️  Starting React frontend on http://localhost:3000" -ForegroundColor Cyan
$frontendProcess = Start-Process `
    -FilePath "npm" `
    -ArgumentList "run dev" `
    -WorkingDirectory "$scriptDir\frontend" `
    -PassThru `
    -NoNewWindow

Write-Host "`n✅ Both services started!`n" -ForegroundColor Green
Write-Host "  Frontend:  http://localhost:3000" -ForegroundColor Cyan
Write-Host "  Backend:   http://localhost:5000" -ForegroundColor Cyan
Write-Host "`nPress Ctrl+C to stop both services.`n" -ForegroundColor Yellow

# Wait for processes
try {
    $null = $backendProcess.WaitForExit()
}
catch {
    # Cleanup on interrupt
    Stop-Process -Id $frontendProcess.Id -Force -ErrorAction SilentlyContinue
    Stop-Process -Id $backendProcess.Id -Force -ErrorAction SilentlyContinue
}
