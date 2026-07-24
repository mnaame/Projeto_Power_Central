from datetime import datetime

from app.extensions import db
from app.models.types import TZDateTime
from app.utils.time import utcnow

DEPARA_STATUSES = ("OK", "REVISAR", "NAO")
CHAMADO_GATILHOS = ("sem_comunicacao", "disparos", "teste")
CHAMADO_RESULTADOS = ("aberta", "simulada", "falha", "repetida", "sem_depara")


class AuvoDepara(db.Model):
    """De-para conta PowerCentral ↔ cliente Auvo, editável pela tela.
    Só linhas OK com id_auvo preenchido abrem chamado; NAO = cliente que
    não abre; REVISAR = casamento ambíguo aguardando revisão humana.
    Duas contas podem apontar para o mesmo id_auvo (loja + tesouraria =
    mesmo local — válido por especificação)."""

    __tablename__ = "auvo_depara"

    id = db.Column(db.Integer, primary_key=True)
    conta_power = db.Column(db.String(32), nullable=False, unique=True, index=True)
    nome_power = db.Column(db.String(200), nullable=False, default="")
    id_auvo = db.Column(db.Integer, nullable=True)
    nome_auvo = db.Column(db.String(200), nullable=True)
    score = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(16), nullable=False, default="REVISAR")
    # Supressão temporária: a conta continua OK (volta a abrir chamado
    # sozinha), mas fica pausada enquanto o problema é resolvido em campo.
    # suprimido_ate = None e suprimido = True → pausa por tempo indefinido
    # (até liberar na mão); com data → volta a abrir sozinha quando passa.
    suprimido = db.Column(db.Boolean, nullable=False, default=False)
    suprimido_ate = db.Column(TZDateTime, nullable=True)
    suprimido_motivo = db.Column(db.String(200), nullable=True)
    updated_at = db.Column(TZDateTime, nullable=False, default=utcnow, onupdate=utcnow)
    updated_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    updated_by = db.relationship("User", foreign_keys=[updated_by_user_id])

    __table_args__ = (
        db.CheckConstraint("status IN ('OK', 'REVISAR', 'NAO')", name="ck_auvo_depara_status"),
    )

    def esta_suprimido(self, agora: datetime) -> bool:
        """True enquanto a conta está pausada. Uma data de expiração no
        passado libera a conta sozinha (não precisa desmarcar na mão)."""
        if not self.suprimido:
            return False
        if self.suprimido_ate is not None and agora >= self.suprimido_ate:
            return False
        return True

    @property
    def abre_chamado(self) -> bool:
        return self.status == "OK" and self.id_auvo is not None

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuvoDepara {self.conta_power} -> {self.id_auvo} ({self.status})>"


class AuvoChamado(db.Model):
    """Histórico de cada tentativa de abertura de chamado na Auvo. O
    cooldown de dedup deriva daqui: só a última linha 'aberta' (criação
    real) de uma conta bloqueia reabertura — 'simulada' nunca bloqueia
    (em simulação não se persiste estado de dedup, por especificação).
    Em falha, request_body/response_body guardam o diagnóstico."""

    __tablename__ = "auvo_chamados"

    id = db.Column(db.Integer, primary_key=True)
    criado_em = db.Column(TZDateTime, nullable=False, default=utcnow, index=True)
    gatilho = db.Column(db.String(24), nullable=False, index=True)
    conta_power = db.Column(db.String(32), nullable=True, index=True)
    cliente = db.Column(db.String(200), nullable=True)
    resultado = db.Column(db.String(16), nullable=False, index=True)
    id_tarefa_auvo = db.Column(db.String(64), nullable=True)
    origem_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    request_body = db.Column(db.JSON, nullable=True)
    response_body = db.Column(db.JSON, nullable=True)
    erro = db.Column(db.Text, nullable=True)

    origem = db.relationship("User", foreign_keys=[origem_user_id])

    __table_args__ = (
        db.CheckConstraint(
            "gatilho IN ('sem_comunicacao', 'disparos', 'teste')",
            name="ck_auvo_chamados_gatilho",
        ),
        db.CheckConstraint(
            "resultado IN ('aberta', 'simulada', 'falha', 'repetida', 'sem_depara')",
            name="ck_auvo_chamados_resultado",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuvoChamado {self.gatilho} {self.conta_power} {self.resultado}>"
