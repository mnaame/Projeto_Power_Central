from app.extensions import db
from app.models.types import TZDateTime
from app.utils.time import utcnow


class AuditoriaHorarioSnapshot(db.Model):
    """Último resultado da varredura de horários.

    Existe por dois motivos. O primeiro é o card do dashboard: a varredura
    consulta o portal uma vez por conta e leva minutos, então não pode
    rodar a cada carregamento de tela — o card lê daqui e mostra "atualizado
    em <data>".

    O segundo é a própria tela do módulo: o resultado fica gravado, então
    uma varredura que terminou continua visível mesmo que o navegador tenha
    desistido de esperar a resposta.

    `itens` guarda a lista inteira (conta, nome, tipo, resumo) — são
    centenas de linhas curtas, não vale uma tabela filha para isso.
    """

    __tablename__ = "auditoria_horario_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    atualizado_em = db.Column(TZDateTime, nullable=False, default=utcnow, index=True)
    total = db.Column(db.Integer, nullable=False, default=0)
    sem = db.Column(db.Integer, nullable=False, default=0)
    com = db.Column(db.Integer, nullable=False, default=0)
    erros = db.Column(db.Integer, nullable=False, default=0)
    # Tipos auditados nesta execução, como o usuário pediu na tela.
    tipos = db.Column(db.String(200), nullable=False, default="")
    itens = db.Column(db.JSON, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuditoriaHorarioSnapshot {self.atualizado_em} sem={self.sem}>"
