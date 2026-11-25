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

    # Smoke: exe sem console grava o resultado em %APPDATA%\MotorTributario\logs\launcher.log
    $Log = Join-Path $env:APPDATA "MotorTributario\logs\launcher.log"
    $Proc = Start-Process -FilePath $Exe -ArgumentList "--smoke" -Wait -PassThru
    Write-Host "Smoke exit code: $($Proc.ExitCode)"
    if (Test-Path $Log) { Get-Content $Log -Tail 1 }
    exit $Proc.ExitCode
}
finally {
    Pop-Location
}
