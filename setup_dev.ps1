<#
.SYNOPSIS
    Setup do ambiente de desenvolvimento — Motor Tributário Conect
.DESCRIPTION
    Script one-shot para configurar tudo que é necessário para trabalhar no projeto.
    Rode como: .\setup_dev.ps1
#>

$ErrorActionPreference = "Continue"
Write-Host "`n🔧 MOTOR TRIBUTÁRIO CONECT — Setup do Ambiente de Desenvolvimento" -ForegroundColor Cyan
Write-Host "=" * 65 -ForegroundColor DarkGray

# ────────────────────────────────────────────────────────────────
# 1. Execution Policy
# ────────────────────────────────────────────────────────────────
Write-Host "`n[1/7] Verificando ExecutionPolicy..." -ForegroundColor Yellow
$policy = Get-ExecutionPolicy -Scope CurrentUser
if ($policy -eq "Restricted") {
    Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force
    Write-Host "  ✅ ExecutionPolicy alterada para RemoteSigned" -ForegroundColor Green
} else {
    Write-Host "  ✅ ExecutionPolicy OK ($policy)" -ForegroundColor Green
}

# ────────────────────────────────────────────────────────────────
# 2. Python
# ────────────────────────────────────────────────────────────────
Write-Host "`n[2/7] Verificando Python..." -ForegroundColor Yellow
try {
    $pyVer = python --version 2>&1
    Write-Host "  ✅ Python global: $pyVer" -ForegroundColor Green
} catch {
    Write-Host "  ❌ Python NÃO encontrado! Instale: winget install Python.Python.3.12" -ForegroundColor Red
}

# ────────────────────────────────────────────────────────────────
# 3. uv
# ────────────────────────────────────────────────────────────────
Write-Host "`n[3/7] Verificando uv..." -ForegroundColor Yellow
try {
    $uvVer = uv --version 2>&1
    Write-Host "  ✅ $uvVer" -ForegroundColor Green
} catch {
    Write-Host "  ❌ uv NÃO encontrado! Instale: winget install astral-sh.uv" -ForegroundColor Red
}

# ────────────────────────────────────────────────────────────────
# 4. Virtual environment
# ────────────────────────────────────────────────────────────────
Write-Host "`n[4/7] Verificando virtual environment..." -ForegroundColor Yellow
$venvPython = Join-Path $PSScriptRoot "PY\.venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $venvVer = & $venvPython --version 2>&1
    Write-Host "  ✅ venv: $venvVer" -ForegroundColor Green
    
    # Verificar deps
    $pydantic = & $venvPython -c "import pydantic; print(pydantic.__version__)" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✅ pydantic: $pydantic" -ForegroundColor Green
    } else {
        Write-Host "  ⚠️  pydantic não instalado! Rode: uv pip install -r PY/requirements.txt" -ForegroundColor Yellow
    }
} else {
    Write-Host "  ❌ venv NÃO encontrado! Criando..." -ForegroundColor Red
    Set-Location (Join-Path $PSScriptRoot "PY")
    uv venv .venv
    uv pip install -r requirements.txt
    Write-Host "  ✅ venv criado e deps instaladas" -ForegroundColor Green
}

# ────────────────────────────────────────────────────────────────
# 5. Node.js + markdownlint
# ────────────────────────────────────────────────────────────────
Write-Host "`n[5/7] Verificando Node.js..." -ForegroundColor Yellow
try {
    $nodeVer = node --version 2>&1
    Write-Host "  ✅ Node.js: $nodeVer" -ForegroundColor Green
} catch {
    Write-Host "  ❌ Node.js NÃO encontrado! Instalando..." -ForegroundColor Red
    winget install OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
}

Write-Host "`n[6/7] Verificando markdownlint-cli2..." -ForegroundColor Yellow
try {
    $mdVer = markdownlint-cli2 --help 2>&1 | Select-Object -First 1
    Write-Host "  ✅ markdownlint-cli2 instalado" -ForegroundColor Green
} catch {
    Write-Host "  ⚠️  markdownlint-cli2 não encontrado. Instalando..." -ForegroundColor Yellow
    npm install -g markdownlint-cli2
}

# ────────────────────────────────────────────────────────────────
# 7. Git
# ────────────────────────────────────────────────────────────────
Write-Host "`n[7/7] Verificando Git..." -ForegroundColor Yellow
try {
    $gitVer = git --version 2>&1
    Write-Host "  ✅ $gitVer" -ForegroundColor Green
} catch {
    Write-Host "  ❌ Git NÃO encontrado! Instale: winget install Git.Git" -ForegroundColor Red
}

# ────────────────────────────────────────────────────────────────
# Resumo
# ────────────────────────────────────────────────────────────────
Write-Host "`n" + "=" * 65 -ForegroundColor DarkGray
Write-Host "🏁 Setup concluído!" -ForegroundColor Cyan
Write-Host @"

Próximos passos:
  1. Reabra o VS Code neste projeto
  2. Instale as extensões recomendadas (popup vai aparecer)
  3. Selecione o interpretador Python: Ctrl+Shift+P > Python: Select Interpreter
     → Escolha: PY\.venv\Scripts\python.exe
  4. Rode os testes: cd PY && python -m pytest tests/ -v

"@ -ForegroundColor White
