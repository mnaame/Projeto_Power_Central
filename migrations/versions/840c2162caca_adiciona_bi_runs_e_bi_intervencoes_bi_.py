"""Adiciona bi_runs e bi_intervencoes (BI Eficácia do Técnico)

Revision ID: 840c2162caca
Revises: 93f1310def76
Create Date: 2026-08-01 12:24:07.542238

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '840c2162caca'
down_revision = '93f1310def76'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('bi_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.Column('criado_por_user_id', sa.Integer(), nullable=True),
    sa.Column('periodo_desde', sa.DateTime(), nullable=False),
    sa.Column('periodo_hasta', sa.DateTime(), nullable=False),
    sa.Column('janela_dias', sa.Integer(), nullable=False),
    sa.Column('limiar_melhora_pct', sa.Float(), nullable=False),
    sa.Column('limiar_piora_pct', sa.Float(), nullable=False),
    sa.Column('tecnico_filtro', sa.String(length=200), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('erro_mensagem', sa.Text(), nullable=True),
    sa.Column('resumo', sa.JSON(), nullable=True),
    sa.CheckConstraint("status IN ('running', 'success', 'error')", name='ck_bi_runs_status'),
    sa.ForeignKeyConstraint(['criado_por_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('bi_runs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_bi_runs_criado_em'), ['criado_em'], unique=False)

    op.create_table('bi_intervencoes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=False),
    sa.Column('task_id_auvo', sa.String(length=64), nullable=True),
    sa.Column('conta_power', sa.String(length=32), nullable=False),
    sa.Column('id_auvo_cliente', sa.Integer(), nullable=True),
    sa.Column('nome_loja', sa.String(length=200), nullable=False),
    sa.Column('tecnico_nome', sa.String(length=200), nullable=False),
    sa.Column('marco', sa.DateTime(), nullable=False),
    sa.Column('antes_por_dia', sa.Float(), nullable=False),
    sa.Column('depois_por_dia', sa.Float(), nullable=False),
    sa.Column('variacao_pct', sa.Float(), nullable=True),
    sa.Column('classificacao', sa.String(length=16), nullable=False),
    sa.Column('parcial', sa.Boolean(), nullable=False),
    sa.Column('atribuicao_compartilhada', sa.Boolean(), nullable=False),
    sa.Column('dias_depois', sa.Integer(), nullable=False),
    sa.CheckConstraint("classificacao IN ('MELHOROU', 'PIOROU', 'ESTAVEL', 'SEM_BASE')", name='ck_bi_intervencoes_classificacao'),
    sa.ForeignKeyConstraint(['run_id'], ['bi_runs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('bi_intervencoes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_bi_intervencoes_classificacao'), ['classificacao'], unique=False)
        batch_op.create_index(batch_op.f('ix_bi_intervencoes_conta_power'), ['conta_power'], unique=False)
        batch_op.create_index(batch_op.f('ix_bi_intervencoes_marco'), ['marco'], unique=False)
        batch_op.create_index(batch_op.f('ix_bi_intervencoes_run_id'), ['run_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_bi_intervencoes_tecnico_nome'), ['tecnico_nome'], unique=False)


def downgrade():
    with op.batch_alter_table('bi_intervencoes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_bi_intervencoes_tecnico_nome'))
        batch_op.drop_index(batch_op.f('ix_bi_intervencoes_run_id'))
        batch_op.drop_index(batch_op.f('ix_bi_intervencoes_marco'))
        batch_op.drop_index(batch_op.f('ix_bi_intervencoes_conta_power'))
        batch_op.drop_index(batch_op.f('ix_bi_intervencoes_classificacao'))

    op.drop_table('bi_intervencoes')
    with op.batch_alter_table('bi_runs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_bi_runs_criado_em'))

    op.drop_table('bi_runs')
