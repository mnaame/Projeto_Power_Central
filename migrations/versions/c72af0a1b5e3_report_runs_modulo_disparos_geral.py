"""report_runs: aceita o módulo 'disparos_geral'

Revision ID: c72af0a1b5e3
Revises: f48ebb3d3cf7
Create Date: 2026-07-27

"""
from alembic import op
import sqlalchemy as sa


revision = "c72af0a1b5e3"
down_revision = "f48ebb3d3cf7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("report_runs", schema=None) as batch_op:
        batch_op.drop_constraint("ck_report_runs_module", type_="check")
        batch_op.create_check_constraint(
            "ck_report_runs_module",
            "module IN ('atendimentos', 'disparos', 'disparos_geral')",
        )


def downgrade():
    with op.batch_alter_table("report_runs", schema=None) as batch_op:
        batch_op.drop_constraint("ck_report_runs_module", type_="check")
        batch_op.create_check_constraint(
            "ck_report_runs_module",
            "module IN ('atendimentos', 'disparos')",
        )
