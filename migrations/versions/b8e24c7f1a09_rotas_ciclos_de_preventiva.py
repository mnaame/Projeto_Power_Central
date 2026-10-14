"""rotas_ciclos: rodadas de preventiva com marca de visita

Revision ID: b8e24c7f1a09
Revises: a3f70c1d8b24
Create Date: 2026-10-14 10:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8e24c7f1a09'
down_revision = 'a3f70c1d8b24'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'rotas_ciclos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('numero', sa.Integer(), nullable=False),
        sa.Column('iniciado_em', sa.DateTime(timezone=True), nullable=False),
        sa.Column('encerrado_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('atualizado_em', sa.DateTime(timezone=True), nullable=False),
        sa.Column('criado_por_user_id', sa.Integer(), nullable=True),
        sa.Column('resumo', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['criado_por_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'rotas_ciclo_clientes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ciclo_id', sa.Integer(), nullable=False),
        sa.Column('conta', sa.String(length=16), nullable=False),
        sa.Column('nome', sa.String(length=200), nullable=False),
        sa.Column('bairro', sa.String(length=120), nullable=False),
        sa.Column('cidade', sa.String(length=120), nullable=False),
        sa.Column('fonte', sa.String(length=32), nullable=False),
        sa.Column('visitado_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('visitado_por_user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['ciclo_id'], ['rotas_ciclos.id']),
        sa.ForeignKeyConstraint(['visitado_por_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('rotas_ciclo_clientes', schema=None) as batch_op:
        batch_op.create_index(
            'ix_rotas_ciclo_clientes_ciclo_id', ['ciclo_id'], unique=False
        )
        batch_op.create_index(
            'ix_rotas_ciclo_clientes_conta', ['conta'], unique=False
        )


def downgrade():
    with op.batch_alter_table('rotas_ciclo_clientes', schema=None) as batch_op:
        batch_op.drop_index('ix_rotas_ciclo_clientes_conta')
        batch_op.drop_index('ix_rotas_ciclo_clientes_ciclo_id')
    op.drop_table('rotas_ciclo_clientes')
    op.drop_table('rotas_ciclos')
