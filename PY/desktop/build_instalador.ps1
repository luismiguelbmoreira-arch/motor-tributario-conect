<#
.SYNOPSIS
    Gera PY\dist\instalador\MotorTributario-Setup-<versão>.exe com o Inno Setup 6.
.DESCRIPTION
    Rodar depois de build_exe.ps1 (precisa de PY\dist\MotorTributario\MotorTributario.exe):
        powershell -ExecutionPolicy Bypass -File PY\desktop\build_instalador.ps1
    Inno Setup 6 (ISCC.exe) é ferramenta de build, não dependência do app. Procura em
    $env:INNO_ISCC, Program Files e %LOCALAPPDATA%\Programs. A versão vem de main.py (FastAPI version=).
    Antes de compilar, recusa o dist se houver banco, .env ou segredo dentro dele.
#>
param([string]$Versao = "")
$ErrorActionPreference = "Stop"
$PyDir = Split-Path -Parent $PSScriptRoot
$Dist = Join-Path $PyDir "dist\MotorTributario"
$Exe = Join-Path $Dist "MotorTributario.exe"
if (-not (Test-Path $Exe)) { throw "Exe não encontrado em $Exe. Rode antes desktop\build_exe.ps1." }

if (-not $Versao) {
    $m = Select-String -Path (Join-Path $PyDir "main.py") -Pattern '^\s*version="([0-9][^"]*)"' | Select-Object -First 1
    if (-not $m) { throw "Versão não encontrada em main.py; passe -Versao." }
    $Versao = $m.Matches[0].Groups[1].Value
}

# Banco, cópia de banco, .env, chave, segredo, log e PDF não entram no pacote. Padrões largos
# de propósito: o que é legítimo e casa com eles vai em $Permitidos (caminho relativo ao dist).
$Proibidos = @(
    "*.db", "*.db-*", "*.db.*", "*.sqlite", "*.sqlite3", "*.sqlite-*", "*.bak",
    ".env", ".env.*", "*.env",
    "master.key", "*.key", "*.pem", "*.pfx", "*.p12",
    "jwt_secret*", "senha_inicial_admin*",
    "*.log", "*.pdf"
)
$Permitidos = @("_internal\certifi\cacert.pem")  # CAs públicas do certifi: HTTPS da API da Anthropic
$DistAbs = (Resolve-Path $Dist).Path.TrimEnd('\') + '\'
$Achados = @(Get-ChildItem -Path $Dist -Recurse -File -Force -Include $Proibidos -ErrorAction SilentlyContinue |
    Where-Object { $Permitidos -notcontains $_.FullName.Substring($DistAbs.Length) })
if ($Achados.Count) { throw "dist tem arquivo proibido (banco/segredo/log/PDF): $($Achados.Name -join ', ')" }

$Candidatos = @(
    $env:INNO_ISCC,
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
) | Where-Object { $_ -and (Test-Path $_) }
if (-not $Candidatos) { throw "ISCC.exe (Inno Setup 6) não encontrado. Instale: winget install JRSoftware.InnoSetup  ou defina INNO_ISCC." }
$Iscc = @($Candidatos)[0]

$Saida = Join-Path $PyDir "dist\instalador"
& $Iscc "/DAppVersion=$Versao" "/DDistDir=$Dist" "/DOutputDir=$Saida" (Join-Path $PSScriptRoot "instalador.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC falhou ($LASTEXITCODE)" }
$Setup = Join-Path $Saida "MotorTributario-Setup-$Versao.exe"
$Hash = (Get-FileHash $Setup -Algorithm SHA256).Hash
Write-Host "Instalador: $Setup"
Write-Host "SHA-256: $Hash"
