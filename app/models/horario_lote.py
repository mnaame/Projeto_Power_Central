from app.extensions import db
from app.models.types import TZDateTime
from app.utils.time import utcnow

LOTE_STATUSES = ("preparado", "aplicando", "aplicado", "parcial", "error")
ITEM_STATUSES = (
    "pendente",
    "aplicado",
    "simulado",
    "manual",
    "invalido",
    "ja_aplicado",
    "divergente",
    "erro",
)


class AjusteHorarioLote(db.Model):
    """Uma varredura de horários preparada para ajuste em lote.

    O lote inteiro é persistido, e não só um registro do que foi gravado,
    por três razões que se reforçam:

    1. **É o backup.** Os itens guardam o fechamento ANTES de qualquer
       escrita — é daqui que sai o `.xlsx` de desfazer.
    2. **Aplica-se exatamente o que foi revisado.** A varredura leva
       minutos; se o "aplicar" varresse de novo, o admin estaria
       confirmando uma lista e executando outra.
    3. **É o ledger da idempotência.** Item com `aplicado` não é tocado de
       novo numa segunda execução.
    """

    __tablename__ = "ajuste_horario_lotes"

    id = db.Column(db.Integer, primary_key=True)
    criado_em = db.Column(TZDateTime, nullable=False, default=utcnow, index=True)
    criado_por_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    delta_min = db.Column(db.Integer, nullable=False)
    # Fotografado na criação: saber DEPOIS se aquele lote rodou em
    # simulação é o que separa "não mudou nada" de "mudou e deu errado".
    simulacao = db.Column(db.Boolean, nullable=False, default=True)
    status = db.Column(db.String(16), nullable=False, default="preparado")
    contas_varridas = db.Column(db.Integer, nullable=False, default=0)
    erro_mensagem = db.Column(db.Text, nullable=True)
    aplicado_em = db.Column(TZDateTime, nullable=True)

    criado_por = db.relationship("User", foreign_keys=[criado_por_user_id])
    itens = db.relationship(
        "AjusteHorarioItem",
        backref="lote",
        order_by="AjusteHorarioItem.id",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('preparado', 'aplicando', 'aplicado', 'parcial', 'error')",
            name="ck_ajuste_horario_lotes_status",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AjusteHorarioLote #{self.id} delta={self.delta_min} {self.status}>"


class AjusteHorarioItem(db.Model):
    """Uma linha de horário do portal dentro do lote.

    `antes` é o valor lido na preparação e **nunca é reescrito**: é a
    referência do desfazer e da checagem de idempotência (só grava se o
    portal ainda estiver exatamente nesse valor)."""

    __tablename__ = "ajuste_horario_itens"

    id = db.Column(db.Integer, primary_key=True)
    lote_id = db.Column(
        db.Integer, db.ForeignKey("ajuste_horario_lotes.id"), nullable=False, index=True
    )
    horario_id = db.Column(db.String(32), nullable=False, index=True)
    cue_iid = db.Column(db.String(32), nullable=False, default="")
    conta = db.Column(db.String(32), nullable=False, default="")
    nome = db.Column(db.String(200), nullable=False, default="")
    dia_abertura = db.Column(db.Integer, nullable=False, default=0)
    hora_abertura = db.Column(db.String(16), nullable=False, default="")
    dia_fechamento = db.Column(db.Integer, nullable=False, default=0)
    antes = db.Column(db.String(16), nullable=False, default="")
    depois = db.Column(db.String(16), nullable=False, default="")
    categoria = db.Column(db.String(16), nullable=False, default="aplicar", index=True)
    status = db.Column(db.String(16), nullable=False, default="pendente", index=True)
    erro_mensagem = db.Column(db.Text, nullable=True)
    aplicado_em = db.Column(TZDateTime, nullable=True)

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('pendente', 'aplicado', 'simulado', 'manual', 'invalido',"
            " 'ja_aplicado', 'divergente', 'erro')",
            name="ck_ajuste_horario_itens_status",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AjusteHorarioItem {self.conta} {self.antes}->{self.depois} {self.status}>"
