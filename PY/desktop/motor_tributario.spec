# -*- mode: python ; coding: utf-8 -*-
# PyInstaller — Motor Tributário Conect desktop (onedir).
# Gerar: PY\desktop\build_exe.ps1   (ou: pyinstaller PY/desktop/motor_tributario.spec)
#
# Lista FECHADA de arquivos de dados. Nunca incluir PY/ ou data/ inteiros:
# levaria .env, *.db, backups e PDFs cifrados de auditoria para dentro do .exe.
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

DESKTOP_DIR = SPECPATH  # noqa: F821 — injetado pelo PyInstaller
PY_DIR = os.path.abspath(os.path.join(DESKTOP_DIR, ".."))
REPO_DIR = os.path.abspath(os.path.join(PY_DIR, ".."))
sys.path.insert(0, PY_DIR)  # collect_submodules("api") precisa achar PY/api

datas = [
    (os.path.join(REPO_DIR, "UI"), "UI"),
    (os.path.join(PY_DIR, "alembic"), "alembic"),
    (os.path.join(PY_DIR, "alembic.ini"), "."),
]

hiddenimports = [
    # passlib carrega o handler pelo nome — PyInstaller não enxerga.
    "passlib.handlers.bcrypt",
    # routers importados dentro de main.py depois do app.
    *collect_submodules("api"),
]

excludes = [
    "playwright",  # orquestrador e-CAC real — fora do app desktop
    "pytest",
    "_pytest",
    "tests",
    "tkinter",
]

a = Analysis(  # noqa: F821
    [os.path.join(DESKTOP_DIR, "launcher.py")],
    pathex=[PY_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MotorTributario",
    console=False,  # janela nativa, sem console
    upx=False,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name="MotorTributario",
    upx=False,
)
