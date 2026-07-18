from app.extensions import db
from app.utils.time import utcnow

CYCLE_STATUSES = ("running", "success", "error")
CYCLE_SOURCES = ("scheduled", "manual", "watchdog")
CLASSIFICATIONS = ("sem_comunicacao", "falso_positivo")
ALERT_MESSAGE_TYPES = ("entrada", "saida", "normalizacao", "watchdog", "watchdog_recovery")


class CollectionCycle(db.Model):
    """Um ciclo do coletor (RF1). O snapshot mais recente com status=success
    representa o estado "atual" do sistema — não existe tabela de estado
    separada."""

    __tablename__ = "collection_cycles"

    id = db.Column(db.Integer, primary_key=True)
    started_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(16), nullable=False, default="running")
    source = db.Column(db.String(16), nullable=False, default="scheduled")
    triggered_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    total_em_falha_tst = db.Column(db.Integer, nullable=True)
    total_sem_comunicacao = db.Column(db.Integer, nullable=True)
    total_falso_positivo = db.Column(db.Integer, nullable=True)

    accounts = db.relationship(
        "CycleAccount", backref="cycle", cascade="all, delete-orphan", lazy="dynamic"
    )
    alerts = db.relationship(
        "AlertSent", backref="cycle", cascade="all, delete-orphan", lazy="dynamic"
    )

    __table_args__ = (
        db.CheckConstraint("status IN ('running', 'success', 'error')", name="ck_cycles_status"),
        db.CheckConstraint(
            "source IN ('scheduled', 'manual', 'watchdog')", name="ck_cycles_source"
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CollectionCycle {self.id} {self.status}/{self.source}>"


class CycleAccount(db.Model):
    """Snapshot de uma conta dentro de um ciclo. A série completa destas
    linhas alimenta o histórico e o gráfico de evolução."""

    __tablename__ = "cycle_accounts"

    id = db.Column(db.Integer, primary_key=True)
    cycle_id = db.Column(
        db.Integer, db.ForeignKey("collection_cycles.id"), nullable=False, index=True
    )
    account_number = db.Column(db.String(32), nullable=False, index=True)
    account_name = db.Column(db.String(255), nullable=True)
    tst_failure_since = db.Column(db.DateTime, nullable=True)
    last_event_code = db.Column(db.String(16), nullable=True)
    last_event_at = db.Column(db.DateTime, nullable=True)
    classification = db.Column(db.String(20), nullable=False)

    __table_args__ = (
        db.CheckConstraint(
            "classification IN ('sem_comunicacao', 'falso_positivo')",
            name="ck_cycle_accounts_classification",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CycleAccount {self.account_number} {self.classification}>"


class AlertSent(db.Model):
    """Registro auditável de cada alerta Telegram disparado (regra 6.4)."""

    __tablename__ = "alerts_sent"

    id = db.Column(db.Integer, primary_key=True)
    cycle_id = db.Column(
        db.Integer, db.ForeignKey("collection_cycles.id"), nullable=False, index=True
    )
    sent_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    message_type = db.Column(db.String(24), nullable=False)
    accounts_added = db.Column(db.JSON, nullable=True)
    accounts_removed = db.Column(db.JSON, nullable=True)
    success = db.Column(db.Boolean, nullable=False, default=False)
    telegram_message_id = db.Column(db.String(64), nullable=True)

    __table_args__ = (
        db.CheckConstraint(
            "message_type IN ('entrada', 'saida', 'normalizacao', 'watchdog', 'watchdog_recovery')",
            name="ck_alerts_sent_message_type",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AlertSent {self.message_type} cycle={self.cycle_id}>"
