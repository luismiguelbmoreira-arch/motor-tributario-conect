"""fase5 paginas fantasmas — ownership de diagnosticos + settings de user

Revision ID: 49832cc28f45
Revises: 2789f587b143
Create Date: 2026-04-23 18:00:00.000000

Fase 5 — habilita histórico e configurações:

1. `diagnosticos.uploaded_by_user_id` (FK users.id, nullable, indexed)
   → ERR-050: sem essa coluna, `/auditorias` não tinha como filtrar por dono
     e listar diagnósticos seria IDOR grave (qualquer autenticado via tudo).
     Nullable para não quebrar registros antigos criados antes da Fase 5.

2. `users.tema` (string, default 'auto')
   → Preferência visual. Literal aceito pelo endpoint: claro|escuro|auto.

3. `users.notificacoes_email` (bool, default True)
   → Preferência de notificação. Só persiste a flag — disparo real de email
     não é escopo da Fase 5 (fora do escopo no plano).

Amparo:
  - LGPD Art. 6º V (minimização) — ownership permite devolver apenas o que
    é do próprio usuário.
  - LGPD Art. 46 §1º (segurança) — impede vazamento IDOR horizontal.
  - CTN Art. 195 (retenção 5 anos) — registros antigos (uploaded_by_user_id
    NULL) permanecem no banco para prova fiscal, só ficam fora da listagem
    pessoal do histórico.

NOTA: reescrita manual (autogenerate detecta drift de tabelas antigas
como `atividades`). Esta migração trata APENAS das 3 mudanças da Fase 5.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '49832cc28f45'
down_revision: Union[str, Sequence[str], None] = '2789f587b143'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Adiciona:
      - diagnosticos.uploaded_by_user_id (nullable, FK users.id) + índice
      - users.tema (string default 'auto')
      - users.notificacoes_email (bool default True)

    SQLite ALTER TABLE limitado → batch_alter_table emula via drop+recreate.
    """
    # 1. diagnosticos — ownership
    with op.batch_alter_table('diagnosticos', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('uploaded_by_user_id', sa.Integer(), nullable=True),
        )
        batch_op.create_foreign_key(
            'fk_diagnosticos_uploaded_by_user_id',
            'users',
            ['uploaded_by_user_id'],
            ['id'],
        )
        batch_op.create_index(
            batch_op.f('ix_diagnosticos_uploaded_by_user_id'),
            ['uploaded_by_user_id'],
            unique=False,
        )

    # 2+3. users — preferências
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'tema',
                sa.String(length=10),
                nullable=False,
                server_default='auto',
            ),
        )
        batch_op.add_column(
            sa.Column(
                'notificacoes_email',
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )


def downgrade() -> None:
    """Reverte as 3 colunas adicionadas."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('notificacoes_email')
        batch_op.drop_column('tema')

    with op.batch_alter_table('diagnosticos', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_diagnosticos_uploaded_by_user_id'))
        batch_op.drop_constraint(
            'fk_diagnosticos_uploaded_by_user_id',
            type_='foreignkey',
        )
        batch_op.drop_column('uploaded_by_user_id')
