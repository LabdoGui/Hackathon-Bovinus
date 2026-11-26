<#
.SYNOPSIS
  Instala o PratoCusto AI no Windows (ambiente virtual, dependencias, .env e banco).
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1
  powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1 -Demo
.PARAMETER Demo
  Tambem cria os dados de demonstracao (FICTICIOS).
#>
param(
    [switch]$Demo
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Test-Python312 {
    param([string]$Exe, [string[]]$ExeArgs)
    try {
        $out = & $Exe @ExeArgs --version 2>&1
        return ($LASTEXITCODE -eq 0 -and "$out" -match "Python 3\.12")
    } catch {
        return $false
    }
}

$pyExe = $null
$pyArgs = @()
if (Test-Python312 "py" @("-3.12")) {
    $pyExe = "py"
    $pyArgs = @("-3.12")
} elseif (Test-Python312 "python" @()) {
    $pyExe = "python"
}
if (-not $pyExe) {
    Write-Host "Python 3.12 nao encontrado." -ForegroundColor Red
    Write-Host "Instale em https://www.python.org/downloads/ (marque 'Add python.exe to PATH') ou execute:"
    Write-Host "  winget install Python.Python.3.12"
    exit 1
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Criando ambiente virtual (.venv)..."
    & $pyExe @pyArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Falha ao criar o ambiente virtual." }
}
$python = Join-Path (Get-Location) ".venv\Scripts\python.exe"

Write-Host "Instalando dependencias..."
& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Falha ao atualizar o pip." }
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar as dependencias." }

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Arquivo .env criado a partir do .env.example. Revise-o antes de usar em producao."
} else {
    Write-Host "Arquivo .env ja existe; mantido."
}

Write-Host "Preparando o banco de dados..."
& $python -m app.cli migrate
if ($LASTEXITCODE -ne 0) { throw "Falha ao aplicar as migracoes." }

if ($Demo) {
    & $python -m app.cli seed
    if ($LASTEXITCODE -ne 0) { throw "Falha ao criar os dados de demonstracao." }
}

Write-Host ""
Write-Host "Instalacao concluida." -ForegroundColor Green
Write-Host "Proximos passos:"
Write-Host "  1) Crie uma chave de administrador (aparece uma unica vez):"
Write-Host "       .venv\Scripts\python.exe -m app.cli create-operator --name Administrador --username admin --role admin"
Write-Host "  2) Inicie o sistema:  iniciar.bat   (ou scripts\iniciar.ps1)"
Write-Host "  3) Abra http://127.0.0.1:8000/dashboard"
