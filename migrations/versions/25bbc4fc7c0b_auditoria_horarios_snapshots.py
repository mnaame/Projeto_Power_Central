"""auditoria horarios snapshots

Revision ID: 25bbc4fc7c0b
Revises: c4a1d7f92b30
Create Date: 2026-09-21 13:17:07.859949

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '25bbc4fc7c0b'
down_revision = 'c4a1d7f92b30'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auditoria_horario_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("sem", sa.Integer(), nullable=False),
        sa.Column("com", sa.Integer(), nullable=False),
        sa.Column("erros", sa.Integer(), nullable=False),
        sa.Column("tipos", sa.String(length=200), nullable=False),
        sa.Column("itens", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("auditoria_horario_snapshots", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_auditoria_horario_snapshots_atualizado_em"),
            ["atualizado_em"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("auditoria_horario_snapshots", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_auditoria_horario_snapshots_atualizado_em"))
    op.drop_table("auditoria_horario_snapshots")
