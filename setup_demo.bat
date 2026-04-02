@echo off
chcp 65001 >nul
title Motor Tributário Conect — Setup

echo.
echo  ============================================================
echo   Motor Tributário Conect 2026-2033 — Setup Inicial
echo  ============================================================
echo.

:: Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERRO] Python nao encontrado!
    echo.
    echo  Instale o Python 3.11+ em: https://www.python.org/downloads/
    echo  IMPORTANTE: marque "Add Python to PATH" durante a instalacao.
    echo.
    pause
    exit /b 1
)

echo  Python encontrado:
python --version
echo.

:: Instalar dependências
echo  Instalando dependencias (pode demorar alguns minutos)...
echo.
pip install -r PY\requirements.txt
if errorlevel 1 (
    echo.
    echo  [ERRO] Falha ao instalar dependencias.
    echo  Tente rodar o CMD como Administrador.
    pause
    exit /b 1
)

echo.
echo  ============================================================
echo   Setup concluido! Iniciando o sistema...
echo  ============================================================
echo.

python run_demo.py

pause
