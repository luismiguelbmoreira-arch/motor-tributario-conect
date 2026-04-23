"""fase4.1 auditoria tentativas acesso IDOR

Revision ID: 2789f587b143
Revises: 0e962f81f935
Create Date: 2026-04-23 16:45:22.726082

Cria a tabela `auditoria_tentativas_acesso` que registra incidentes de
segurança onde um usuário autenticado tentou acessar recurso de outro
(IDOR horizontal — vetor do ERR-018).

Amparo:
  - LGPD Art. 37  — registro de operações de tratamento.
  - LGPD Art. 46 §1º — medidas de segurança da informação.
  - LGPD Art. 48  — evidência em caso de incidente reportável à ANPD.
  - CTN  Art. 195 — retenção mínima de 5 anos (consistência com
                    `auditoria_documentos`).

NOTA: reescrita manualmente porque o autogenerate detectou drift de
outras tabelas (`atividades`) por diferenças entre o banco local e o
metadata SQLModel atual. Esta migração trata APENAS da nova tabela
da Fase 4.1 — drift de `atividades` não é escopo.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '2789f587b143'
down_revision: Union[str, Sequence[str], None] = '0e962f81f935'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Cria `auditoria_tentativas_acesso` + índices."""
    op.create_table(
        'auditoria_tentativas_acesso',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('analise_id_prefix', sqlmodel.sql.sqltypes.AutoString(length=8), nullable=False),
        sa.Column('user_id_tentando', sa.Integer(), nullable=False),
        sa.Column('user_id_dono', sa.Integer(), nullable=True),
        sa.Column('ip', sqlmodel.sql.sqltypes.AutoString(length=45), nullable=False),
        sa.Column('tentado_em', sa.DateTime(), nullable=False),
        sa.Column('endpoint', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.ForeignKeyConstraint(['user_id_dono'], ['users.id'], ),
        sa.ForeignKeyConstraint(['user_id_tentando'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('auditoria_tentativas_acesso', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_auditoria_tentativas_acesso_analise_id_prefix'),
            ['analise_id_prefix'], unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_auditoria_tentativas_acesso_user_id_tentando'),
            ['user_id_tentando'], unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_auditoria_tentativas_acesso_tentado_em'),
            ['tentado_em'], unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_auditoria_tentativas_acesso_endpoint'),
            ['endpoint'], unique=False,
        )


def downgrade() -> None:
    """Remove `auditoria_tentativas_acesso` + índices."""
    with op.batch_alter_table('auditoria_tentativas_acesso', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_auditoria_tentativas_acesso_endpoint'))
        batch_op.drop_index(batch_op.f('ix_auditoria_tentativas_acesso_tentado_em'))
        batch_op.drop_index(batch_op.f('ix_auditoria_tentativas_acesso_user_id_tentando'))
        batch_op.drop_index(batch_op.f('ix_auditoria_tentativas_acesso_analise_id_prefix'))
    op.drop_table('auditoria_tentativas_acesso')
