from app.extensions import db
from app.models.types import TZDateTime
from app.utils.time import utcnow

HORIZONTES = ("fixa", "semana", "dia")
PRIORIDADES = ("baixa", "media", "alta")
STATUSES = ("pendente", "feito")


class Tarefa(db.Model):
    """Tarefa pessoal do usuário logado (Fixa/Semana/Dia). Cada usuário só
    enxerga e edita as próprias — toda leitura/escrita filtra por
    `user_id`, nunca confia só no `id` da URL."""

    __tablename__ = "tarefas"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    titulo = db.Column(db.String(300), nullable=False)
    descricao = db.Column(db.Text, nullable=True)
    horizonte = db.Column(db.String(16), nullable=False, index=True)
    data = db.Column(db.Date, nullable=True)
    prioridade = db.Column(db.String(16), nullable=False, default="media")
    status = db.Column(db.String(16), nullable=False, default="pendente", index=True)
    ordem = db.Column(db.Integer, nullable=False, default=0)
    criado_em = db.Column(TZDateTime, nullable=False, default=utcnow)
    concluido_em = db.Column(TZDateTime, nullable=True)

    __table_args__ = (
        db.CheckConstraint(
            "horizonte IN ('fixa', 'semana', 'dia')", name="ck_tarefas_horizonte"
        ),
        db.CheckConstraint(
            "prioridade IN ('baixa', 'media', 'alta')", name="ck_tarefas_prioridade"
        ),
        db.CheckConstraint("status IN ('pendente', 'feito')", name="ck_tarefas_status"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Tarefa #{self.id} {self.titulo!r} {self.horizonte}/{self.status}>"
