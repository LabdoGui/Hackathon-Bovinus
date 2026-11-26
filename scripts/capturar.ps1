<#
.SYNOPSIS
  Tira uma foto pela API e baixa o arquivo para a pasta PrecoCusto.
.EXAMPLE
  .\scripts\capturar.ps1
  .\scripts\capturar.ps1 -Arquivo "C:\caminho\foto.jpg"   # envia uma imagem existente em vez de usar a camera
#>
param(
    [string]$Destino = (Join-Path ([Environment]::GetFolderPath("Desktop")) "PrecoCusto"),
    [string]$Api = "http://127.0.0.1:8000/api/v1",
    [string]$Arquivo
)
$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Destino)) { New-Item -ItemType Directory -Path $Destino | Out-Null }

if ($Arquivo) {
    # Windows PowerShell 5.1 nao tem -Form: usa curl.exe para o multipart
    $json = curl.exe -s -f -X POST "$Api/camera/uploads" -F "file=@$Arquivo"
    if ($LASTEXITCODE -ne 0) { throw "Falha ao enviar $Arquivo" }
    $captura = $json | ConvertFrom-Json
} else {
    $captura = Invoke-RestMethod -Method Post -Uri "$Api/camera/captures"
}

$ext = switch ($captura.mime_type) { "image/png" { "png" } "image/webp" { "webp" } default { "jpg" } }
$nome = "foto_{0:yyyyMMdd_HHmmss}_{1}.{2}" -f (Get-Date), $captura.id.Substring(0, 8), $ext
$caminho = Join-Path $Destino $nome

Invoke-WebRequest -Uri "$Api/camera/captures/$($captura.id)/image" -OutFile $caminho -UseBasicParsing

Write-Host "Foto salva em: $caminho" -ForegroundColor Green
Write-Host "ID da captura: $($captura.id)  ($($captura.width)x$($captura.height))"
if ($captura.warnings.Count) { Write-Host "Avisos: $($captura.warnings -join ', ')" -ForegroundColor Yellow }
