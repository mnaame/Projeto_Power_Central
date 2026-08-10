"""central_cliente_links aceita status 'removido'

Revision ID: d90d1780e01f
Revises: e53b6bc95cf8
Create Date: 2026-08-10 19:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd90d1780e01f'
down_revision = 'e53b6bc95cf8'
branch_labels = None
depends_on = None

_STATUS_NOVOS = "('pendente', 'criado', 'erro', 'removido')"
_STATUS_ANTIGOS = "('pendente', 'criado', 'erro')"


def upgrade():
    with op.batch_alter_table('central_cliente_links', schema=None) as batch_op:
        batch_op.drop_constraint('ck_central_cliente_links_status', type_='check')
        batch_op.create_check_constraint(
            'ck_central_cliente_links_status', f"status IN {_STATUS_NOVOS}"
        )


def downgrade():
    with op.batch_alter_table('central_cliente_links', schema=None) as batch_op:
        batch_op.drop_constraint('ck_central_cliente_links_status', type_='check')
        batch_op.create_check_constraint(
            'ck_central_cliente_links_status', f"status IN {_STATUS_ANTIGOS}"
        )
