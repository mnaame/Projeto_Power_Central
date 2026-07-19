"""alerts_sent aceita message_type 'periodico'

Revision ID: 7c41d2a90b3e
Revises: 1e57a3e9f1c4
Create Date: 2026-07-19 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7c41d2a90b3e'
down_revision = '1e57a3e9f1c4'
branch_labels = None
depends_on = None

_TIPOS_NOVOS = "('entrada', 'saida', 'normalizacao', 'watchdog', 'watchdog_recovery', 'periodico')"
_TIPOS_ANTIGOS = "('entrada', 'saida', 'normalizacao', 'watchdog', 'watchdog_recovery')"


def upgrade():
    with op.batch_alter_table('alerts_sent', schema=None) as batch_op:
        batch_op.drop_constraint('ck_alerts_sent_message_type', type_='check')
        batch_op.create_check_constraint(
            'ck_alerts_sent_message_type', f"message_type IN {_TIPOS_NOVOS}"
        )


def downgrade():
    with op.batch_alter_table('alerts_sent', schema=None) as batch_op:
        batch_op.drop_constraint('ck_alerts_sent_message_type', type_='check')
        batch_op.create_check_constraint(
            'ck_alerts_sent_message_type', f"message_type IN {_TIPOS_ANTIGOS}"
        )
