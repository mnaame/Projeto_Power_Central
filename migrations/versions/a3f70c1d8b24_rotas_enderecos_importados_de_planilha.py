"""rotas_enderecos: endereços importados de planilha

Revision ID: a3f70c1d8b24
Revises: 75732a4a0cb5
Create Date: 2026-10-13 16:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a3f70c1d8b24'
down_revision = '75732a4a0cb5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'rotas_enderecos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('fonte', sa.String(length=32), nullable=False),
        sa.Column('conta_power', sa.String(length=16), nullable=True),
        sa.Column('id_auvo', sa.Integer(), nullable=True),
        sa.Column('nome', sa.String(length=200), nullable=False),
        sa.Column('nome_norm', sa.String(length=200), nullable=False),
        sa.Column('bairro', sa.String(length=120), nullable=False),
        sa.Column('cidade', sa.String(length=120), nullable=False),
        sa.Column('uf', sa.String(length=2), nullable=False),
        sa.Column('cep', sa.String(length=12), nullable=False),
        sa.Column('endereco_bruto', sa.Text(), nullable=False),
        sa.Column('importado_em', sa.DateTime(timezone=True), nullable=False),
        sa.Column('importado_por_user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['importado_por_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('rotas_enderecos', schema=None) as batch_op:
        batch_op.create_index('ix_rotas_enderecos_fonte', ['fonte'], unique=False)
        batch_op.create_index(
            'ix_rotas_enderecos_conta_power', ['conta_power'], unique=False
        )
        batch_op.create_index('ix_rotas_enderecos_id_auvo', ['id_auvo'], unique=False)
        batch_op.create_index(
            'ix_rotas_enderecos_nome_norm', ['nome_norm'], unique=False
        )


def downgrade():
    with op.batch_alter_table('rotas_enderecos', schema=None) as batch_op:
        batch_op.drop_index('ix_rotas_enderecos_nome_norm')
        batch_op.drop_index('ix_rotas_enderecos_id_auvo')
        batch_op.drop_index('ix_rotas_enderecos_conta_power')
        batch_op.drop_index('ix_rotas_enderecos_fonte')
    op.drop_table('rotas_enderecos')
