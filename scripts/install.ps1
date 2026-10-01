# Instalação guiada do Agent Hangar (Windows/PowerShell): confere Python e Docker, instala o CLI num ambiente isolado
# (.hangar\venv) e roda `hangar setup`. Ex.: powershell -ExecutionPolicy Bypass -File scripts\install.ps1
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
$py = Get-Command py -ErrorAction SilentlyContinue  # PowerShell 5.1: sem o operador ??
if (-not $py) { $py = Get-Command python -ErrorAction SilentlyContinue }
if (-not $py) { Write-Host 'Python 3.10+ é necessário: https://www.python.org/downloads/'; exit 1 }
$pyExe = $py.Source
& $pyExe -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'
if ($LASTEXITCODE -ne 0) { Write-Host 'Python 3.10+ é necessário.'; exit 1 }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Write-Host 'Docker não encontrado: instale o Docker Desktop.'; exit 1 }
if (-not (Test-Path '.hangar\venv\Scripts\python.exe')) {
  New-Item -ItemType Directory -Force '.hangar' | Out-Null
  & $pyExe -m venv .hangar\venv
}
& .hangar\venv\Scripts\python.exe -m pip install -q --upgrade pip
& .hangar\venv\Scripts\python.exe -m pip install -q .\cli
Write-Host 'CLI instalado em .hangar\venv (atalho: .hangar\venv\Scripts\hangar.exe)'
& .hangar\venv\Scripts\hangar.exe setup --dir . @args
exit $LASTEXITCODE
