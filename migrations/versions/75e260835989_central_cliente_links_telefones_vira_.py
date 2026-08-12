"""central_cliente_links telefones vira lista

Revision ID: 75e260835989
Revises: ecae4d947f47
Create Date: 2026-08-12 16:47:37.953819

"""
import json

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '75e260835989'
down_revision = 'ecae4d947f47'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('central_cliente_links', schema=None) as batch_op:
        batch_op.add_column(sa.Column('telefones', sa.JSON(), nullable=True))

    conn = op.get_bind()
    linhas = conn.execute(
        sa.text("SELECT id, telefone FROM central_cliente_links WHERE telefone IS NOT NULL")
    ).fetchall()
    for linha in linhas:
        conn.execute(
            sa.text("UPDATE central_cliente_links SET telefones = :telefones WHERE id = :id"),
            {"telefones": json.dumps([linha.telefone]), "id": linha.id},
        )

    with op.batch_alter_table('central_cliente_links', schema=None) as batch_op:
        batch_op.drop_column('telefone')


def downgrade():
    with op.batch_alter_table('central_cliente_links', schema=None) as batch_op:
        batch_op.add_column(sa.Column('telefone', sa.String(length=20), nullable=True))

    conn = op.get_bind()
    linhas = conn.execute(
        sa.text("SELECT id, telefones FROM central_cliente_links WHERE telefones IS NOT NULL")
    ).fetchall()
    for linha in linhas:
        lista = json.loads(linha.telefones) if linha.telefones else []
        primeiro = lista[0] if lista else None
        conn.execute(
            sa.text("UPDATE central_cliente_links SET telefone = :telefone WHERE id = :id"),
            {"telefone": primeiro, "id": linha.id},
        )

    with op.batch_alter_table('central_cliente_links', schema=None) as batch_op:
        batch_op.drop_column('telefones')
