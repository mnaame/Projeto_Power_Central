from app.extensions import db
from app.models.types import TZDateTime
from app.utils.time import utcnow

RUN_STATUSES = ("running", "success", "error")
CLASSIFICACOES = ("MELHOROU", "PIOROU", "ESTAVEL", "SEM_BASE")


class BiRun(db.Model):
    """Um recálculo do BI de Eficácia do Técnico — a chamada cara (agenda
    da Auvo + histórico de disparos da PowerCentral) roda uma vez aqui;
    o dashboard só lê `BiIntervencao` do run mais recente. `resumo`
    guarda os contadores agregados (mesmo padrão de
    `ReportRun.extra_counts`), incluindo `sem_vinculo` — tarefas
    concluídas sem de-para OK, que ficam de fora do cálculo."""

    __tablename__ = "bi_runs"

    id = db.Column(db.Integer, primary_key=True)
    criado_em = db.Column(TZDateTime, nullable=False, default=utcnow, index=True)
    criado_por_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    periodo_desde = db.Column(TZDateTime, nullable=False)
    periodo_hasta = db.Column(TZDateTime, nullable=False)
    janela_dias = db.Column(db.Integer, nullable=False)
    limiar_melhora_pct = db.Column(db.Float, nullable=False)
    limiar_piora_pct = db.Column(db.Float, nullable=False)
    tecnico_filtro = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(16), nullable=False, default="running")
    erro_mensagem = db.Column(db.Text, nullable=True)
    resumo = db.Column(db.JSON, nullable=True)

    criado_por = db.relationship("User", foreign_keys=[criado_por_user_id])
    intervencoes = db.relationship(
        "BiIntervencao",
        backref="run",
        order_by="BiIntervencao.marco.desc()",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        db.CheckConstraint("status IN ('running', 'success', 'error')", name="ck_bi_runs_status"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<BiRun #{self.id} {self.periodo_desde}..{self.periodo_hasta} {self.status}>"


class BiIntervencao(db.Model):
    """Uma ordem concluída na Auvo (com de-para OK) transformada em
    intervenção medida: disparos válidos por dia antes × depois da
    conclusão. `variacao_pct` fica nulo em SEM_BASE (não dá para dividir
    por zero disparo antes)."""

    __tablename__ = "bi_intervencoes"

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey("bi_runs.id"), nullable=False, index=True)
    task_id_auvo = db.Column(db.String(64), nullable=True)
    conta_power = db.Column(db.String(32), nullable=False, index=True)
    id_auvo_cliente = db.Column(db.Integer, nullable=True)
    nome_loja = db.Column(db.String(200), nullable=False, default="")
    tecnico_nome = db.Column(db.String(200), nullable=False, default="", index=True)
    marco = db.Column(TZDateTime, nullable=False, index=True)
    antes_por_dia = db.Column(db.Float, nullable=False)
    depois_por_dia = db.Column(db.Float, nullable=False)
    variacao_pct = db.Column(db.Float, nullable=True)
    classificacao = db.Column(db.String(16), nullable=False, index=True)
    parcial = db.Column(db.Boolean, nullable=False, default=False)
    atribuicao_compartilhada = db.Column(db.Boolean, nullable=False, default=False)
    dias_depois = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (
        db.CheckConstraint(
            "classificacao IN ('MELHOROU', 'PIOROU', 'ESTAVEL', 'SEM_BASE')",
            name="ck_bi_intervencoes_classificacao",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<BiIntervencao {self.conta_power} {self.classificacao} {self.marco}>"
