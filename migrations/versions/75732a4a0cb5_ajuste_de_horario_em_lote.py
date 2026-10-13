"""ajuste de horario em lote

Revision ID: 75732a4a0cb5
Revises: 8c1d9f9a0adc
Create Date: 2026-10-13 11:59:36.463088

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '75732a4a0cb5'
down_revision = '8c1d9f9a0adc'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ajuste_horario_lotes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("criado_por_user_id", sa.Integer(), nullable=True),
        sa.Column("delta_min", sa.Integer(), nullable=False),
        sa.Column("simulacao", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("contas_varridas", sa.Integer(), nullable=False),
        sa.Column("erro_mensagem", sa.Text(), nullable=True),
        sa.Column("aplicado_em", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('preparado', 'aplicando', 'aplicado', 'parcial', 'error')",
            name="ck_ajuste_horario_lotes_status",
        ),
        sa.ForeignKeyConstraint(["criado_por_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("ajuste_horario_lotes", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_ajuste_horario_lotes_criado_em"), ["criado_em"], unique=False
        )

    op.create_table(
        "ajuste_horario_itens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lote_id", sa.Integer(), nullable=False),
        sa.Column("horario_id", sa.String(length=32), nullable=False),
        sa.Column("cue_iid", sa.String(length=32), nullable=False),
        sa.Column("conta", sa.String(length=32), nullable=False),
        sa.Column("nome", sa.String(length=200), nullable=False),
        sa.Column("dia_abertura", sa.Integer(), nullable=False),
        sa.Column("hora_abertura", sa.String(length=16), nullable=False),
        sa.Column("dia_fechamento", sa.Integer(), nullable=False),
        sa.Column("antes", sa.String(length=16), nullable=False),
        sa.Column("depois", sa.String(length=16), nullable=False),
        sa.Column("categoria", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("erro_mensagem", sa.Text(), nullable=True),
        sa.Column("aplicado_em", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pendente', 'aplicado', 'simulado', 'manual', 'invalido',"
            " 'ja_aplicado', 'divergente', 'erro')",
            name="ck_ajuste_horario_itens_status",
        ),
        sa.ForeignKeyConstraint(["lote_id"], ["ajuste_horario_lotes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("ajuste_horario_itens", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_ajuste_horario_itens_lote_id"), ["lote_id"])
        batch_op.create_index(batch_op.f("ix_ajuste_horario_itens_horario_id"), ["horario_id"])
        batch_op.create_index(batch_op.f("ix_ajuste_horario_itens_categoria"), ["categoria"])
        batch_op.create_index(batch_op.f("ix_ajuste_horario_itens_status"), ["status"])


def downgrade():
    op.drop_table("ajuste_horario_itens")
    with op.batch_alter_table("ajuste_horario_lotes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_ajuste_horario_lotes_criado_em"))
    op.drop_table("ajuste_horario_lotes")
