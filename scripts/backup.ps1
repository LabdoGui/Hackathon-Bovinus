<#
.SYNOPSIS
  Cria um backup verificado do banco SQLite (pasta data\backups). Serve para o Agendador de Tarefas.
.EXAMPLE
  schtasks /Create /SC DAILY /ST 23:30 /TN "PratoCusto Backup" /TR "powershell -NoProfile -ExecutionPolicy Bypass -File C:\PratoCusto\scripts\backup.ps1"
#>
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$python = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Ambiente virtual nao encontrado. Execute primeiro: scripts\instalar.ps1" -ForegroundColor Red
    exit 1
}

& $python -m app.cli backup
exit $LASTEXITCODE
