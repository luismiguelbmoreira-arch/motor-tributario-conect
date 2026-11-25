"""Trava o que importa no script do instalador (desktop/instalador.iss).

Não compila (Inno Setup não roda no CI Linux): só lê o texto e garante que
segredos/banco ficam fora do pacote, que a instalação é por usuário e que a
desinstalação nunca apaga os dados de %APPDATA%.
"""
import fnmatch
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
    excluidos = m.group(1).split(",")
    for nome in ("motor_tributario.db", ".env", "master.key", "jwt_secret", "senha_inicial_admin.txt"):
        assert _casa(nome, excluidos), nome


def test_instalacao_por_usuario_sem_admin():
    setup = _secao("Setup")
    assert re.search(r"^PrivilegesRequired=lowest$", setup, re.M)
    assert re.search(r"^DefaultDirName=\{autopf\}", setup, re.M)


def test_appid_fixo():
    assert re.search(r"^AppId=\{\{[0-9A-F-]{36}\}$", _secao("Setup"), re.M)


def test_desinstalacao_so_remove_o_que_instalou():
    # Sem [UninstallDelete]: "filesandordirs {app}" apagaria uma pasta escolhida pelo
    # usuário que já existia com outros arquivos; {userappdata} apagaria banco e segredos.
    assert not re.search(r"^\[UninstallDelete\]", _texto(), re.M)


def test_atualizacao_apaga_so_as_migrations_antigas():
    # Migration removida numa versão nova não pode sobrar no disco para o Alembic ler.
    linhas = _secao("InstallDelete").splitlines()
    assert linhas == ['Type: filesandordirs; Name: "{app}\\_internal\\alembic\\versions"']


# Nomes que passavam pela lista antiga (revisão do Bugkilla, testados com arquivos falsos).
NOMES_SENSIVEIS = (
    ".env", ".env.local", ".env.production", "motor_tributario.db", "banco.db-wal",
    "banco.db-journal", "banco.db.bak", "copia.sqlite", "copia.sqlite3", "master.key",
    "chave.pem", "jwt_secret", "jwt_secret.tmp", "senha_inicial_admin.txt", "launcher.log",
    "cliente.pdf",
)
PS1 = os.path.join(os.path.dirname(__file__), "..", "desktop", "build_instalador.ps1")


def _lista_ps1(nome: str) -> list[str]:
    with open(PS1, encoding="utf-8") as f:
        texto = f.read()
    m = re.search(rf"^\${nome} = @\((.*?)\)\s*(#.*)?$", texto, re.M | re.S)
    assert m, f"${nome} ausente em build_instalador.ps1"
    return re.findall(r'"([^"]+)"', m.group(1))


def _casa(nome: str, padroes) -> bool:
    return any(fnmatch.fnmatchcase(nome.lower(), p.lower()) for p in padroes)


def test_build_recusa_nomes_sensiveis():
    proibidos = _lista_ps1("Proibidos")
    soltos = [n for n in NOMES_SENSIVEIS if not _casa(n, proibidos)]
    assert soltos == []


def test_build_so_permite_o_cacert_do_certifi():
    assert _lista_ps1("Permitidos") == ["_internal\\certifi\\cacert.pem"]


def test_iss_exclui_nomes_sensiveis_menos_pem():
    m = re.search(r'Excludes:\s*"([^"]*)"', _secao("Files"))
    excluidos = m.group(1).split(",")
    assert not _casa("cacert.pem", excluidos)  # o certifi precisa dele para HTTPS
    soltos = [n for n in NOMES_SENSIVEIS if not n.endswith(".pem") and not _casa(n, excluidos)]
    assert soltos == []
