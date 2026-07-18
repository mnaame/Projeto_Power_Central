from app.extensions import db


class WatchdogState(db.Model):
    """Estado do watchdog (RF8). Tabela de linha única — a criação/garantia
    do singleton é responsabilidade da camada de serviço (Fase 2)."""

    __tablename__ = "watchdog_state"

    id = db.Column(db.Integer, primary_key=True)
    last_successful_cycle_at = db.Column(db.DateTime, nullable=True)
    alert_active = db.Column(db.Boolean, nullable=False, default=False)
    alert_sent_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<WatchdogState alert_active={self.alert_active}>"
