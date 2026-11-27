# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — Motor Tributário Conect (Windows, onedir)
#
# Build (a partir de PY/):  powershell -File desktop\build_exe.ps1
# Saída:                    PY\dist\MotorTributario\MotorTributario.exe
#
# Empacota SÓ o necessário: código de PY/ alcançável a partir do launcher + UI/.
# NUNCA inclui .env, *.db, data/ do repositório nem segredos.

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

PY_DIR = Path(SPECPATH).resolve().parent  # noqa: F821 — SPECPATH injetado pelo PyInstaller
REPO_DIR = PY_DIR.parent

hiddenimports = []
# passlib carrega handlers por nome em runtime (CryptContext(schemes=["bcrypt"]))
hiddenimports += collect_submodules("passlib.handlers")
# Pacotes do próprio projeto: garante routers/serviços importados de forma indireta
for pkg in ("api", "core", "database", "schemas", "services", "utils", "observability", "parsers"):
    hiddenimports += collect_submodules(pkg)
# Alembic carrega env.py e versions/*.py do disco e importa seus módulos em runtime
hiddenimports += collect_submodules("alembic")

# alembic/ vai em disco (_internal/alembic), sem __pycache__: env.py + versions/*.py
ALEMBIC_DIR = PY_DIR / "alembic"
datas = [(str(REPO_DIR / "UI"), "UI")]
datas += [(str(ALEMBIC_DIR / nome), "alembic") for nome in ("env.py", "script.py.mako")]
datas += [(str(p), "alembic/versions") for p in sorted((ALEMBIC_DIR / "versions").glob("*.py"))]

a = Analysis(  # noqa: F821
    [str(PY_DIR / "desktop" / "launcher.py")],
    pathex=[str(PY_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "_pytest", "tests", "ruff", "IPython", "tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MotorTributario",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="MotorTributario",
)
