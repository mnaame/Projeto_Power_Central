"""central_cliente_links marca de whatsapp enviado

Revision ID: c4a1d7f92b30
Revises: 75e260835989
Create Date: 2026-08-25 11:20:14.882301

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4a1d7f92b30'
down_revision = '75e260835989'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('central_cliente_links', schema=None) as batch_op:
        batch_op.add_column(sa.Column('whatsapp_enviado_em', sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column('whatsapp_enviado_por_user_id', sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            'fk_central_cliente_links_whatsapp_enviado_por_user_id',
            'users',
            ['whatsapp_enviado_por_user_id'],
            ['id'],
        )


def downgrade():
    with op.batch_alter_table('central_cliente_links', schema=None) as batch_op:
        batch_op.drop_constraint(
            'fk_central_cliente_links_whatsapp_enviado_por_user_id', type_='foreignkey'
        )
        batch_op.drop_column('whatsapp_enviado_por_user_id')
        batch_op.drop_column('whatsapp_enviado_em')
