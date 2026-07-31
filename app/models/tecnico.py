from app.extensions import db
from app.models.types import TZDateTime
from app.utils.time import utcnow

LOTE_STATUSES = ("running", "success", "parcial", "error")
ITEM_STATUSES = ("pendente", "gerado", "erro", "sem_depara", "nao_selecionado")


class TecnicoLote(db.Model):
    """Uma execução do Relatório do Técnico do Dia — ao contrário dos
    outros relatórios (1 execução = 1 arquivo), aqui 1 lote gera N
    arquivos (um por loja da agenda), cada um com seu próprio status em
    `TecnicoLoteItem`. `status` do lote resume os itens: success = todos
    gerados, parcial = mistura de gerado/erro, error = nenhum gerado."""

    __tablename__ = "tecnico_lotes"

    id = db.Column(db.Integer, primary_key=True)
    criado_em = db.Column(TZDateTime, nullable=False, default=utcnow, index=True)
    criado_por_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    data_agenda = db.Column(db.String(10), nullable=False)
    tecnico_id_auvo = db.Column(db.Integer, nullable=True)
    tecnico_nome = db.Column(db.String(200), nullable=False, default="")
    periodo_desde = db.Column(TZDateTime, nullable=False)
    periodo_hasta = db.Column(TZDateTime, nullable=False)
    codigos_globais = db.Column(db.JSON, nullable=False)
    status = db.Column(db.String(16), nullable=False, default="running")
    erro_mensagem = db.Column(db.Text, nullable=True)

    criado_por = db.relationship("User", foreign_keys=[criado_por_user_id])
    itens = db.relationship(
        "TecnicoLoteItem",
        backref="lote",
        order_by="TecnicoLoteItem.id",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('running', 'success', 'parcial', 'error')",
            name="ck_tecnico_lotes_status",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TecnicoLote #{self.id} {self.data_agenda} {self.tecnico_nome} {self.status}>"


class TecnicoLoteItem(db.Model):
    """Uma loja dentro de um lote — falha isolada: erro numa loja não
    derruba as demais. `codigos_usados` guarda os códigos efetivamente
    usados (herdados do lote ou override feito na tela antes de gerar)."""

    __tablename__ = "tecnico_lote_itens"

    id = db.Column(db.Integer, primary_key=True)
    lote_id = db.Column(
        db.Integer, db.ForeignKey("tecnico_lotes.id"), nullable=False, index=True
    )
    conta_power = db.Column(db.String(32), nullable=True)
    id_auvo_cliente = db.Column(db.Integer, nullable=True)
    nome_loja = db.Column(db.String(200), nullable=False, default="")
    horario_agenda = db.Column(db.String(32), nullable=True)
    codigos_usados = db.Column(db.JSON, nullable=False)
    status = db.Column(db.String(16), nullable=False, default="pendente", index=True)
    erro_mensagem = db.Column(db.Text, nullable=True)
    arquivo_path = db.Column(db.String(500), nullable=True)
    gerado_em = db.Column(TZDateTime, nullable=True)

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('pendente', 'gerado', 'erro', 'sem_depara', 'nao_selecionado')",
            name="ck_tecnico_lote_itens_status",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TecnicoLoteItem {self.conta_power} {self.nome_loja} {self.status}>"
