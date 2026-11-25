<#
.SYNOPSIS
    Gera PY\dist\MotorTributario\MotorTributario.exe (PyInstaller onedir).
.DESCRIPTION
    Rodar a partir de qualquer pasta:  powershell -ExecutionPolicy Bypass -File PY\desktop\build_exe.ps1
    Pré-requisito: venv em PY\.venv com requirements.txt + requirements-desktop.txt.
    Depois do build roda o .exe com --smoke e mostra o resultado do log.
#>
$ErrorActionPreference = "Stop"
$PyDir = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $PyDir ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "venv não encontrado em $Python" }

Push-Location $PyDir
try {
    & $Python -m PyInstaller --noconfirm --clean `
        --distpath (Join-Path $PyDir "dist") `
        --workpath (Join-Path $PyDir "build") `
        (Join-Path $PSScriptRoot "motor_tributario.spec")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou ($LASTEXITCODE)" }

    $Exe = Join-Path $PyDir "dist\MotorTributario\MotorTributario.exe"
    Write-Host "Build: $Exe"

    # Smoke numa APPDATA temporária: o build não cria banco, jwt_secret nem
    # admin no perfil real. O exe sem console grava o resultado no launcher.log.
    $SmokeAppData = Join-Path ([IO.Path]::GetTempPath()) ("MotorTributario-smoke-" + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $SmokeAppData | Out-Null
    $AppDataReal = $env:APPDATA
    try {
        $env:APPDATA = $SmokeAppData
        $Proc = Start-Process -FilePath $Exe -ArgumentList "--smoke" -Wait -PassThru
    }
    finally {
        $env:APPDATA = $AppDataReal
    }
    $Log = Join-Path $SmokeAppData "MotorTributario\logs\launcher.log"
    Write-Host "Smoke exit code: $($Proc.ExitCode)"
    if (Test-Path $Log) { Get-Content $Log -Tail 1 }
    Remove-Item -Recurse -Force $SmokeAppData
    exit $Proc.ExitCode
}
finally {
    Pop-Location
}
