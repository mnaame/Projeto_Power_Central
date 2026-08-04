"""Adiciona cofre_segredos (Cofre de Senhas)

Revision ID: 077aaab28633
Revises: 840c2162caca
Create Date: 2026-08-04 11:44:10.366864

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '077aaab28633'
down_revision = '840c2162caca'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('cofre_segredos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('titulo', sa.String(length=200), nullable=False),
    sa.Column('categoria', sa.String(length=32), nullable=False),
    sa.Column('login', sa.String(length=200), nullable=True),
    sa.Column('senha_cifrada', sa.Text(), nullable=False),
    sa.Column('url', sa.String(length=500), nullable=True),
    sa.Column('notas_cifradas', sa.Text(), nullable=True),
    sa.Column('nivel', sa.String(length=16), nullable=False),
    sa.Column('criado_por_user_id', sa.Integer(), nullable=True),
    sa.Column('atualizado_por_user_id', sa.Integer(), nullable=True),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(), nullable=False),
    sa.Column('expira_em', sa.Date(), nullable=True),
    sa.CheckConstraint("nivel IN ('equipe', 'restrito')", name='ck_cofre_segredos_nivel'),
    sa.ForeignKeyConstraint(['atualizado_por_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['criado_por_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('cofre_segredos', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_cofre_segredos_categoria'), ['categoria'], unique=False)
        batch_op.create_index(batch_op.f('ix_cofre_segredos_titulo'), ['titulo'], unique=False)


def downgrade():
    with op.batch_alter_table('cofre_segredos', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_cofre_segredos_titulo'))
        batch_op.drop_index(batch_op.f('ix_cofre_segredos_categoria'))

    op.drop_table('cofre_segredos')
