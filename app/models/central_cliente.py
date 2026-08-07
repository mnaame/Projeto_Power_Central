from app.extensions import db
from app.models.types import TZDateTime
from app.utils.time import utcnow

LOTE_STATUSES = ("running", "success", "parcial", "error")
LINK_STATUSES = ("pendente", "criado", "erro")


class CentralClienteLote(db.Model):
    """Uma execução (simulação ou real) de criação de contatos/links da
    Central do Cliente. Mesmo padrão de `TecnicoLote`: um lote, N itens,
    falha isolada por item — `status` do lote resume os itens."""

    __tablename__ = "central_cliente_lotes"

    id = db.Column(db.Integer, primary_key=True)
    criado_em = db.Column(TZDateTime, nullable=False, default=utcnow, index=True)
    criado_por_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    simulacao = db.Column(db.Boolean, nullable=False, default=True)
    status = db.Column(db.String(16), nullable=False, default="running")
    total_itens = db.Column(db.Integer, nullable=False, default=0)
    total_sucesso = db.Column(db.Integer, nullable=False, default=0)
    total_falha = db.Column(db.Integer, nullable=False, default=0)
    erro_mensagem = db.Column(db.Text, nullable=True)

    criado_por = db.relationship("User", foreign_keys=[criado_por_user_id])
    itens = db.relationship(
        "CentralClienteLink",
        backref="lote",
        order_by="CentralClienteLink.id",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('running', 'success', 'parcial', 'error')",
            name="ck_central_cliente_lotes_status",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CentralClienteLote #{self.id} {self.status} simulacao={self.simulacao}>"


class CentralClienteLink(db.Model):
    """Uma tentativa de criação de contato/link para um cliente Auvo
    dentro de um lote. `id_auvo` **não** é único no banco — uma tentativa
    que falhou pode ser retentada em outro lote; a idempotência ("já tem
    link") é regra de negócio em `central_cliente_service.montar_lote`,
    que só considera linhas com `status == 'criado'`."""

    __tablename__ = "central_cliente_links"

    id = db.Column(db.Integer, primary_key=True)
    lote_id = db.Column(
        db.Integer, db.ForeignKey("central_cliente_lotes.id"), nullable=False, index=True
    )
    id_auvo = db.Column(db.Integer, nullable=False, index=True)
    nome = db.Column(db.String(200), nullable=False, default="")
    contato_codigo = db.Column(db.Integer, nullable=True)
    link_identificador = db.Column(db.String(64), nullable=True)
    link_url = db.Column(db.String(500), nullable=True)
    login = db.Column(db.String(200), nullable=True)
    senha_cifrada = db.Column(db.Text, nullable=True)
    menus = db.Column(db.JSON, nullable=True)
    status = db.Column(db.String(16), nullable=False, default="pendente")
    erro_mensagem = db.Column(db.Text, nullable=True)
    criado_em = db.Column(TZDateTime, nullable=False, default=utcnow)

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('pendente', 'criado', 'erro')",
            name="ck_central_cliente_links_status",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CentralClienteLink id_auvo={self.id_auvo} {self.status}>"
