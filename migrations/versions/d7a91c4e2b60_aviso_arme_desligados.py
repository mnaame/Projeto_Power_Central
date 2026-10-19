"""aviso_arme_desligados: ledger do aviso de arme

Revision ID: d7a91c4e2b60
Revises: c1d35b0e9f72
Create Date: 2026-10-19 17:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd7a91c4e2b60'
down_revision = 'c1d35b0e9f72'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'aviso_arme_desligados',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cue_iid', sa.String(length=16), nullable=False),
        sa.Column('conta', sa.String(length=16), nullable=False),
        sa.Column('nome', sa.String(length=200), nullable=False),
        sa.Column('nnyc_original', sa.Integer(), nullable=False),
        sa.Column('desligado_em', sa.DateTime(timezone=True), nullable=False),
        sa.Column('desligado_por_user_id', sa.Integer(), nullable=True),
        sa.Column('religado_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('religado_por_user_id', sa.Integer(), nullable=True),
        sa.Column('ativo', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['desligado_por_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['religado_por_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('aviso_arme_desligados', schema=None) as batch_op:
        batch_op.create_index(
            'ix_aviso_arme_desligados_cue_iid', ['cue_iid'], unique=False
        )
        batch_op.create_index(
            'ix_aviso_arme_desligados_ativo', ['ativo'], unique=False
        )


def downgrade():
    with op.batch_alter_table('aviso_arme_desligados', schema=None) as batch_op:
        batch_op.drop_index('ix_aviso_arme_desligados_ativo')
        batch_op.drop_index('ix_aviso_arme_desligados_cue_iid')
    op.drop_table('aviso_arme_desligados')
