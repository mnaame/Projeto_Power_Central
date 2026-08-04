from app.extensions import db
from app.models.types import TZDateTime
from app.utils.time import utcnow

NIVEIS = ("equipe", "restrito")

# Sugeridas na tela (select) — não é CheckConstraint no banco, "outro"
# já cobre o que não se encaixa.
CATEGORIAS = ("camera", "roteador", "plataforma", "email", "cliente", "outro")


class Segredo(db.Model):
    """Um item do Cofre de Senhas. `senha_cifrada`/`notas_cifradas` são
    cifradas com Fernet (`VAULT_ENCRYPTION_KEY`, chave dedicada — ver
    services/cofre_service.py); nunca há senha em claro nesta tabela.
    `nivel='equipe'` é visível a qualquer usuário logado; `'restrito'`
    só a admin (checado em cofre_service, não aqui)."""

    __tablename__ = "cofre_segredos"

    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(200), nullable=False, index=True)
    categoria = db.Column(db.String(32), nullable=False, default="outro", index=True)
    login = db.Column(db.String(200), nullable=True)
    senha_cifrada = db.Column(db.Text, nullable=False)
    url = db.Column(db.String(500), nullable=True)
    notas_cifradas = db.Column(db.Text, nullable=True)
    nivel = db.Column(db.String(16), nullable=False, default="equipe")
    criado_por_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    atualizado_por_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    criado_em = db.Column(TZDateTime, nullable=False, default=utcnow)
    atualizado_em = db.Column(TZDateTime, nullable=False, default=utcnow, onupdate=utcnow)
    expira_em = db.Column(db.Date, nullable=True)

    criado_por = db.relationship("User", foreign_keys=[criado_por_user_id])
    atualizado_por = db.relationship("User", foreign_keys=[atualizado_por_user_id])

    __table_args__ = (
        db.CheckConstraint("nivel IN ('equipe', 'restrito')", name="ck_cofre_segredos_nivel"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Segredo {self.titulo!r} ({self.nivel})>"
