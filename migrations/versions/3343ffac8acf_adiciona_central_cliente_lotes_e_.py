"""adiciona central_cliente_lotes e central_cliente_links (Links da Central do Cliente)

Revision ID: 3343ffac8acf
Revises: 077aaab28633
Create Date: 2026-08-07 17:59:22.265954

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3343ffac8acf'
down_revision = '077aaab28633'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('central_cliente_lotes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.Column('criado_por_user_id', sa.Integer(), nullable=True),
    sa.Column('simulacao', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('total_itens', sa.Integer(), nullable=False),
    sa.Column('total_sucesso', sa.Integer(), nullable=False),
    sa.Column('total_falha', sa.Integer(), nullable=False),
    sa.Column('erro_mensagem', sa.Text(), nullable=True),
    sa.CheckConstraint("status IN ('running', 'success', 'parcial', 'error')", name='ck_central_cliente_lotes_status'),
    sa.ForeignKeyConstraint(['criado_por_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('central_cliente_lotes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_central_cliente_lotes_criado_em'), ['criado_em'], unique=False)

    op.create_table('central_cliente_links',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('lote_id', sa.Integer(), nullable=False),
    sa.Column('id_auvo', sa.Integer(), nullable=False),
    sa.Column('nome', sa.String(length=200), nullable=False),
    sa.Column('contato_codigo', sa.Integer(), nullable=True),
    sa.Column('link_identificador', sa.String(length=64), nullable=True),
    sa.Column('link_url', sa.String(length=500), nullable=True),
    sa.Column('login', sa.String(length=200), nullable=True),
    sa.Column('senha_cifrada', sa.Text(), nullable=True),
    sa.Column('menus', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('erro_mensagem', sa.Text(), nullable=True),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.CheckConstraint("status IN ('pendente', 'criado', 'erro')", name='ck_central_cliente_links_status'),
    sa.ForeignKeyConstraint(['lote_id'], ['central_cliente_lotes.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('central_cliente_links', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_central_cliente_links_id_auvo'), ['id_auvo'], unique=False)
        batch_op.create_index(batch_op.f('ix_central_cliente_links_lote_id'), ['lote_id'], unique=False)


def downgrade():
    with op.batch_alter_table('central_cliente_links', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_central_cliente_links_lote_id'))
        batch_op.drop_index(batch_op.f('ix_central_cliente_links_id_auvo'))

    op.drop_table('central_cliente_links')
    with op.batch_alter_table('central_cliente_lotes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_central_cliente_lotes_criado_em'))

    op.drop_table('central_cliente_lotes')
