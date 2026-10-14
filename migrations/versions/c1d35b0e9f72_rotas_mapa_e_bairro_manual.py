"""rotas: coordenadas para o mapa e bairro corrigido à mão

Revision ID: c1d35b0e9f72
Revises: b8e24c7f1a09
Create Date: 2026-10-14 11:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c1d35b0e9f72'
down_revision = 'b8e24c7f1a09'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('rotas_enderecos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('lat', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('lon', sa.Float(), nullable=True))

    with op.batch_alter_table('rotas_ciclo_clientes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('lat', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('lon', sa.Float(), nullable=True))

    op.create_table(
        'rotas_bairros_manuais',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('conta', sa.String(length=16), nullable=False),
        sa.Column('bairro', sa.String(length=120), nullable=False),
        sa.Column('cidade', sa.String(length=120), nullable=False),
        sa.Column('atualizado_em', sa.DateTime(timezone=True), nullable=False),
        sa.Column('atualizado_por_user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['atualizado_por_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('rotas_bairros_manuais', schema=None) as batch_op:
        batch_op.create_index(
            'ix_rotas_bairros_manuais_conta', ['conta'], unique=True
        )


def downgrade():
    with op.batch_alter_table('rotas_bairros_manuais', schema=None) as batch_op:
        batch_op.drop_index('ix_rotas_bairros_manuais_conta')
    op.drop_table('rotas_bairros_manuais')

    with op.batch_alter_table('rotas_ciclo_clientes', schema=None) as batch_op:
        batch_op.drop_column('lon')
        batch_op.drop_column('lat')

    with op.batch_alter_table('rotas_enderecos', schema=None) as batch_op:
        batch_op.drop_column('lon')
        batch_op.drop_column('lat')
