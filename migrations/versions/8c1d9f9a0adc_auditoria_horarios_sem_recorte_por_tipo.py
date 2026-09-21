"""auditoria horarios sem recorte por tipo

Revision ID: 8c1d9f9a0adc
Revises: 25bbc4fc7c0b
Create Date: 2026-09-21 13:28:50.192790

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8c1d9f9a0adc'
down_revision = '25bbc4fc7c0b'
branch_labels = None
depends_on = None


def upgrade():
    """A auditoria passou a varrer TODAS as contas, sem recorte por tipo —
    então a coluna que guardava os tipos auditados na execução não tem mais
    o que guardar."""
    with op.batch_alter_table("auditoria_horario_snapshots", schema=None) as batch_op:
        batch_op.drop_column("tipos")


def downgrade():
    with op.batch_alter_table("auditoria_horario_snapshots", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("tipos", sa.String(length=200), nullable=False, server_default="")
        )
