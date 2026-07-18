from app.extensions import db
from app.utils.time import utcnow

AUDIT_RESULTS = ("success", "failure")


class AuditLog(db.Model):
    """Trilha de auditoria (RF5): login/logout, atualização manual, mudanças
    de configuração/usuários. Só é escrita pela camada de serviço — não há
    rota de edição/remoção pela interface (imutável)."""

    __tablename__ = "audit_log"

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    username_attempted = db.Column(db.String(64), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    action = db.Column(db.String(48), nullable=False, index=True)
    details = db.Column(db.JSON, nullable=True)
    result = db.Column(db.String(16), nullable=False)

    __table_args__ = (
        db.CheckConstraint("result IN ('success', 'failure')", name="ck_audit_log_result"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuditLog {self.action} {self.result}>"
