"""central_cliente_links: coluna telefone (WhatsApp assistido)

Revision ID: e53b6bc95cf8
Revises: 3343ffac8acf
Create Date: 2026-08-10 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e53b6bc95cf8'
down_revision = '3343ffac8acf'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('central_cliente_links', schema=None) as batch_op:
        batch_op.add_column(sa.Column('telefone', sa.String(length=20), nullable=True))


def downgrade():
    with op.batch_alter_table('central_cliente_links', schema=None) as batch_op:
        batch_op.drop_column('telefone')
