<#
.SYNOPSIS
  Inicia o PratoCusto AI (http://127.0.0.1:8000 por padrao). Pare com Ctrl+C.
#>
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$python = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Ambiente virtual nao encontrado. Execute primeiro: scripts\instalar.ps1" -ForegroundColor Red
    exit 1
}

Write-Host "Iniciando o PratoCusto AI... (Ctrl+C para parar)"
Write-Host "  Painel:        http://127.0.0.1:8000/dashboard"
Write-Host "  Documentacao:  http://127.0.0.1:8000/docs"
& $python -m app
exit $LASTEXITCODE
