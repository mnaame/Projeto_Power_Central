from app.extensions import db
from app.models.types import TZDateTime
from app.utils.time import utcnow

REPORT_MODULES = ("atendimentos", "disparos", "disparos_geral")
REPORT_STATUSES = ("running", "success", "error")


class ReportRun(db.Model):
    """Uma geração de relatório (módulos Atendimentos/Disparos). Além do
    histórico auditável, o `period_end` do último run bem-sucedido de
    'disparos' é a origem da janela móvel do próximo relatório."""

    __tablename__ = "report_runs"

    id = db.Column(db.Integer, primary_key=True)
    module = db.Column(db.String(16), nullable=False, index=True)
    generated_at = db.Column(TZDateTime, nullable=False, default=utcnow, index=True)
    generated_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    period_start = db.Column(TZDateTime, nullable=False)
    period_end = db.Column(TZDateTime, nullable=False)
    status = db.Column(db.String(16), nullable=False, default="running")
    error_message = db.Column(db.Text, nullable=True)
    row_count = db.Column(db.Integer, nullable=True)
    extra_counts = db.Column(db.JSON, nullable=True)
    file_path = db.Column(db.String(500), nullable=True)

    generated_by = db.relationship("User", foreign_keys=[generated_by_user_id])

    __table_args__ = (
        db.CheckConstraint(
            "module IN ('atendimentos', 'disparos', 'disparos_geral')",
            name="ck_report_runs_module",
        ),
        db.CheckConstraint(
            "status IN ('running', 'success', 'error')", name="ck_report_runs_status"
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ReportRun {self.module} #{self.id} {self.status}>"
