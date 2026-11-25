"""Trava o que importa no script do instalador (desktop/instalador.iss).

Não compila (Inno Setup não roda no CI Linux): só lê o texto e garante que
segredos/banco ficam fora do pacote, que a instalação é por usuário e que a
desinstalação nunca apaga os dados de %APPDATA%.
"""
import os
import re

ISS = os.path.join(os.path.dirname(__file__), "..", "desktop", "instalador.iss")


def _texto() -> str:
    with open(ISS, encoding="utf-8") as f:
        return f.read()


def _secao(nome: str) -> str:
    m = re.search(rf"^\[{nome}\]\s*$(.*?)(?=^\[|\Z)", _texto(), re.M | re.S)
    assert m, f"seção [{nome}] ausente"
    return "\n".join(
        linha for linha in m.group(1).splitlines() if linha.strip() and not linha.lstrip().startswith(";")
    )


def test_segredos_e_banco_excluidos_do_pacote():
    files = _secao("Files")
    m = re.search(r'Excludes:\s*"([^"]*)"', files)
    assert m, "[Files] sem Excludes"
    excluidos = set(m.group(1).split(","))
    for item in ("*.db", ".env", "master.key", "jwt_secret", "senha_inicial_admin.txt"):
        assert item in excluidos


def test_instalacao_por_usuario_sem_admin():
    setup = _secao("Setup")
    assert re.search(r"^PrivilegesRequired=lowest$", setup, re.M)
    assert re.search(r"^DefaultDirName=\{autopf\}", setup, re.M)


def test_appid_fixo():
    assert re.search(r"^AppId=\{\{[0-9A-F-]{36}\}$", _secao("Setup"), re.M)


def test_desinstalacao_nao_apaga_dados_do_usuario():
    texto = _texto()
    if "[UninstallDelete]" in texto:
        alvo = _secao("UninstallDelete")
        assert "{userappdata}" not in alvo and "{app}" in alvo
    assert "MotorTributario\\motor_tributario.db" not in texto
