# localRAGcoder — Deploy locally from source
#
# Installs the engine as a pip-installable package and runs tests.

param(
    [switch]$Install,
    [switch]$Test,
    [switch]$PWA,
    [switch]$Android,
    [switch]$Windows,
    [switch]$Linux,
    [switch]$All
)

$ErrorActionPreference = "Stop"

function Install-Engine {
    Write-Host "Installing localRAGcoder..." -ForegroundColor Cyan
    pip install -e .
    Write-Host "Installed!" -ForegroundColor Green
}

function Test-Engine {
    Write-Host "Running tests..." -ForegroundColor Cyan
    python run_tests.py --unit
    Write-Host "Tests complete!" -ForegroundColor Green
}

function Build-PWA {
    Write-Host "Building PWA..." -ForegroundColor Cyan
    Set-Location packaging/pwa
    npm install
    npm run build
    Set-Location ../..
    Write-Host "PWA at packaging/pwa/dist/" -ForegroundColor Green
}

function Build-Windows {
    Write-Host "Building Windows EXE..." -ForegroundColor Cyan
    pip install pyinstaller
    pyinstaller --onefile --name localRAGcoder --distpath packaging/windows/dist `
        --add-data "engine;engine" run_tests.py
    Write-Host "EXE at packaging/windows/dist/localRAGcoder.exe" -ForegroundColor Green
}

if ($Install) { Install-Engine }
if ($Test) { Test-Engine }
if ($PWA) { Build-PWA }
if ($Windows) { Build-Windows }
if ($All) {
    Install-Engine
    Test-Engine
    Build-PWA
    Build-Windows
}

if (-not ($Install -or $Test -or $PWA -or $Windows -or $Linux -or $Android -or $All)) {
    Write-Host @"
localRAGcoder — Deploy Script

Usage:
  .\deploy.ps1 -Install     # pip install the engine
  .\deploy.ps1 -Test        # run unit tests
  .\deploy.ps1 -PWA         # build PWA frontend
  .\deploy.ps1 -Windows     # build Windows EXE
  .\deploy.ps1 -All         # do everything

  Cross-platform builds are automated via GitHub Actions (.github/workflows/build.yml)
"@
}
