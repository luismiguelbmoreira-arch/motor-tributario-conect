# Gera o app desktop (onedir) em PY\desktop\dist\MotorTributario\MotorTributario.exe
# Uso (a partir de qualquer pasta):
#   powershell -ExecutionPolicy Bypass -File PY\desktop\build_exe.ps1
# Pré-requisito: venv com requirements.txt + requirements-desktop.txt.
#   Padrão: PY\.venv. Outro Python: -Python C:\caminho\python.exe

param(
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$desktop = $PSScriptRoot
$py = Split-Path $desktop -Parent

if (-not $Python) { $Python = Join-Path $py ".venv\Scripts\python.exe" }
if (-not (Test-Path $Python)) { throw "Python não encontrado: $Python" }

Push-Location $desktop
try {
    & $Python -m PyInstaller --noconfirm --clean `
        --distpath (Join-Path $desktop "dist") `
        --workpath (Join-Path $desktop "build") `
        (Join-Path $desktop "motor_tributario.spec")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou ($LASTEXITCODE)" }

    $dist = Join-Path $desktop "dist\MotorTributario"

    # Trava da regra "nenhum segredo no .exe": falha se algo sensível entrou no pacote.
    $proibidos = Get-ChildItem $dist -Recurse -File -Force | Where-Object {
        ($_.Name -eq ".env") -or ($_.Name -like "*.env") -or ($_.Extension -eq ".db") -or
        ($_.FullName -match "[\\/](auditoria|backups)[\\/]")
    }
    if ($proibidos) { $proibidos | ForEach-Object { Write-Host "PROIBIDO: $($_.FullName)" }; throw "Arquivo sensível no pacote" }
    $comChave = Get-ChildItem $dist -Recurse -File -Include *.py, *.txt, *.ini, *.json, *.js, *.html, *.cfg |
        Select-String -Pattern "sk-ant-[A-Za-z0-9_-]{20,}" -List
    if ($comChave) { $comChave | ForEach-Object { Write-Host "CHAVE: $($_.Path)" }; throw "Chave de API no pacote" }

    # Smoke test: sobe o servidor do próprio .exe, testa /health, /ui/login.html e login (bcrypt), sai.
    $exe = Join-Path $dist "MotorTributario.exe"
    $proc = Start-Process -FilePath $exe -ArgumentList "--smoke" -Wait -PassThru
    if ($proc.ExitCode -ne 0) { throw "Smoke test falhou (código $($proc.ExitCode)). Veja $dist\dados\motor_tributario_desktop.log" }
    Write-Host "OK: $exe (smoke test passou)"
}
finally {
    Pop-Location
}
