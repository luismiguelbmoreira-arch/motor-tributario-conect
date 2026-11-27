"""baseline sincroniza schema com models

Revision ID: a1c3e5f7b9d2
Revises: 49832cc28f45
Create Date: 2026-11-27 05:20:10.002548

Por que existe:
  A cadeia antiga nunca criou `users`, `auditoria_documentos` nem
  `auditoria_acessos` (vinham do `create_all` do app) e deixou `atividades`
  no formato antigo. Resultado: `alembic upgrade head` em banco vazio não
  chegava ao schema dos models. Esta revisão fecha a diferença.

Regras (revisão CONGELADA — não importa models, que mudam com o tempo):
  - Idempotente: cada tabela, coluna, índice e FK só é criado se faltar.
    Banco criado por `create_all` e carimbado em 49832cc28f45 passa sem
    mudança nenhuma.
  - Só cria. Não altera tipo nem nullable de coluna existente (diferenças
    só de tipo VARCHAR↔AutoString ficam como estão: no SQLite são iguais).
  - `atividades` no formato antigo (sem `cnae`):
      vazia     → recriada no formato atual;
      com dados → renomeada para `atividades_legado` (nada é apagado) e a
                  nova é criada vazia.
  - downgrade: no-op documentado. Desfazer apagaria `users` e auditoria
    (LGPD Art. 37 / CTN 173). Restaurar backup é o caminho.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'a1c3e5f7b9d2'
down_revision: Union[str, Sequence[str], None] = '49832cc28f45'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FK_DIAG_USER = 'fk_diagnosticos_uploaded_by_user_id'


def _insp():
    return sa.inspect(op.get_bind())


def _tem_tabela(nome: str) -> bool:
    return _insp().has_table(nome)


def _colunas(tabela: str) -> set:
    return {c['name'] for c in _insp().get_columns(tabela)}


def _indices(tabela: str) -> set:
    return {i['name'] for i in _insp().get_indexes(tabela)}


def _criar_indices(tabela: str, indices) -> None:
    existentes = _indices(tabela)
    for nome, colunas, unico in indices:
        if nome not in existentes:
            op.create_index(nome, tabela, colunas, unique=unico)


def _users() -> None:
    if not _tem_tabela('users'):
        op.create_table(
            'users',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('username', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
            sa.Column('email', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
            sa.Column('hashed_password', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
            sa.Column('role', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
            sa.Column('ativo', sa.Boolean(), nullable=False),
            sa.Column('must_change_password', sa.Boolean(), nullable=False),
            sa.Column('created_at', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('ultimo_acesso', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            sa.Column('tema', sqlmodel.sql.sqltypes.AutoString(length=10), nullable=False),
            sa.Column('notificacoes_email', sa.Boolean(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
    else:
        # `users` antiga (create_all de versão anterior): só soma o que falta.
        faltam = {
            'must_change_password': sa.Column(
                'must_change_password', sa.Boolean(), nullable=False, server_default=sa.false()),
            'tema': sa.Column(
                'tema', sa.String(length=10), nullable=False, server_default='auto'),
            'notificacoes_email': sa.Column(
                'notificacoes_email', sa.Boolean(), nullable=False, server_default=sa.true()),
        }
        existentes = _colunas('users')
        novas = [col for nome, col in faltam.items() if nome not in existentes]
        if novas:
            with op.batch_alter_table('users', schema=None) as batch_op:
                for col in novas:
                    batch_op.add_column(col)
    _criar_indices('users', [
        ('ix_users_email', ['email'], True),
        ('ix_users_username', ['username'], True),
    ])


def _auditoria_documentos() -> None:
    if not _tem_tabela('auditoria_documentos'):
        op.create_table(
            'auditoria_documentos',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('hash_sha256', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
            sa.Column('empresa_cnpj', sqlmodel.sql.sqltypes.AutoString(length=18), nullable=False),
            sa.Column('nome_original', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
            sa.Column('mime_type', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
            sa.Column('tamanho_bytes', sa.Integer(), nullable=False),
            sa.Column('paginas', sa.Integer(), nullable=True),
            sa.Column('storage_path', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False),
            sa.Column('uploaded_at', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('uploaded_by_user_id', sa.Integer(), nullable=True),
            sa.Column('aceito_em', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            sa.Column('aceito_por_user_id', sa.Integer(), nullable=True),
            sa.Column('aceito_ip', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
            sa.Column('diagnostico_id', sa.Integer(), nullable=True),
            sa.Column('purge_after', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('purged_at', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )
    _criar_indices('auditoria_documentos', [
        ('ix_auditoria_documentos_aceito_por_user_id', ['aceito_por_user_id'], False),
        ('ix_auditoria_documentos_diagnostico_id', ['diagnostico_id'], False),
        ('ix_auditoria_documentos_empresa_cnpj', ['empresa_cnpj'], False),
        ('ix_auditoria_documentos_hash_sha256', ['hash_sha256'], True),
        ('ix_auditoria_documentos_uploaded_by_user_id', ['uploaded_by_user_id'], False),
    ])


def _auditoria_acessos() -> None:
    if not _tem_tabela('auditoria_acessos'):
        op.create_table(
            'auditoria_acessos',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('documento_id', sa.Integer(), nullable=False),
            sa.Column('acessado_em', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('acessado_por_user_id', sa.Integer(), nullable=True),
            sa.Column('motivo', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False),
            sa.Column('ip', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
            sa.ForeignKeyConstraint(['documento_id'], ['auditoria_documentos.id']),
            sa.PrimaryKeyConstraint('id'),
        )
    _criar_indices('auditoria_acessos', [
        ('ix_auditoria_acessos_acessado_por_user_id', ['acessado_por_user_id'], False),
        ('ix_auditoria_acessos_documento_id', ['documento_id'], False),
    ])


def _atividades() -> None:
    if _tem_tabela('atividades') and 'cnae' not in _colunas('atividades'):
        # Formato antigo (competencia/receita/anexo...). O índice sai antes:
        # no SQLite ele acompanha a tabela renomeada e o nome colidiria.
        if 'ix_atividades_empresa_id' in _indices('atividades'):
            op.drop_index('ix_atividades_empresa_id', table_name='atividades')
        linhas = op.get_bind().execute(sa.text('SELECT COUNT(*) FROM atividades')).scalar()
        if linhas:
            op.rename_table('atividades', 'atividades_legado')
        else:
            op.drop_table('atividades')
    if not _tem_tabela('atividades'):
        op.create_table(
            'atividades',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('empresa_id', sa.Integer(), nullable=False),
            sa.Column('cnae', sqlmodel.sql.sqltypes.AutoString(length=10), nullable=False),
            sa.Column('descricao', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
            sa.Column('principal', sa.Boolean(), nullable=False),
            sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id']),
            sa.PrimaryKeyConstraint('id'),
        )
    _criar_indices('atividades', [
        ('ix_atividades_empresa_id', ['empresa_id'], False),
    ])


def _fk_diagnosticos_users() -> None:
    tem_fk = any(
        fk.get('referred_table') == 'users'
        and fk.get('constrained_columns') == ['uploaded_by_user_id']
        for fk in _insp().get_foreign_keys('diagnosticos')
    )
    if not tem_fk:
        with op.batch_alter_table('diagnosticos', schema=None) as batch_op:
            batch_op.create_foreign_key(
                _FK_DIAG_USER, 'users', ['uploaded_by_user_id'], ['id'])


def upgrade() -> None:
    """Cria só o que falta para o schema bater com os models."""
    _users()
    _auditoria_documentos()
    _auditoria_acessos()
    _atividades()
    _fk_diagnosticos_users()


def downgrade() -> None:
    """No-op de propósito: ver docstring do módulo (dados de auditoria/LGPD)."""
