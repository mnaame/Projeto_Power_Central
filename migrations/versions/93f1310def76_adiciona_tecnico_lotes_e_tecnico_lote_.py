"""Adiciona tecnico_lotes e tecnico_lote_itens (Relatório do Técnico)

Revision ID: 93f1310def76
Revises: c72af0a1b5e3
Create Date: 2026-07-31 17:10:44.711632

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '93f1310def76'
down_revision = 'c72af0a1b5e3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('tecnico_lotes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.Column('criado_por_user_id', sa.Integer(), nullable=True),
    sa.Column('data_agenda', sa.String(length=10), nullable=False),
    sa.Column('tecnico_id_auvo', sa.Integer(), nullable=True),
    sa.Column('tecnico_nome', sa.String(length=200), nullable=False),
    sa.Column('periodo_desde', sa.DateTime(), nullable=False),
    sa.Column('periodo_hasta', sa.DateTime(), nullable=False),
    sa.Column('codigos_globais', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('erro_mensagem', sa.Text(), nullable=True),
    sa.CheckConstraint("status IN ('running', 'success', 'parcial', 'error')", name='ck_tecnico_lotes_status'),
    sa.ForeignKeyConstraint(['criado_por_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('tecnico_lotes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tecnico_lotes_criado_em'), ['criado_em'], unique=False)

    op.create_table('tecnico_lote_itens',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('lote_id', sa.Integer(), nullable=False),
    sa.Column('conta_power', sa.String(length=32), nullable=True),
    sa.Column('id_auvo_cliente', sa.Integer(), nullable=True),
    sa.Column('nome_loja', sa.String(length=200), nullable=False),
    sa.Column('horario_agenda', sa.String(length=32), nullable=True),
    sa.Column('codigos_usados', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('erro_mensagem', sa.Text(), nullable=True),
    sa.Column('arquivo_path', sa.String(length=500), nullable=True),
    sa.Column('gerado_em', sa.DateTime(), nullable=True),
    sa.CheckConstraint("status IN ('pendente', 'gerado', 'erro', 'sem_depara', 'nao_selecionado')", name='ck_tecnico_lote_itens_status'),
    sa.ForeignKeyConstraint(['lote_id'], ['tecnico_lotes.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('tecnico_lote_itens', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tecnico_lote_itens_lote_id'), ['lote_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tecnico_lote_itens_status'), ['status'], unique=False)


def downgrade():
    with op.batch_alter_table('tecnico_lote_itens', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tecnico_lote_itens_status'))
        batch_op.drop_index(batch_op.f('ix_tecnico_lote_itens_lote_id'))

    op.drop_table('tecnico_lote_itens')
    with op.batch_alter_table('tecnico_lotes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tecnico_lotes_criado_em'))

    op.drop_table('tecnico_lotes')
