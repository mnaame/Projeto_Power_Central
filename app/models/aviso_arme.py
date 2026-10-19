"""Ledger das contas com o aviso de "não armou" desligado.

**Este ledger é a segurança do módulo.** O mecanismo anterior (colocar a
conta em teste) tinha uma janela de tempo que expirava sozinha: esquecer
de desfazer não era possível. Este não tem — o campo fica desligado até
alguém religar.

Então o que impede uma loja de ficar sem supervisão de arme para sempre
não é mais o relógio da plataforma, é esta tabela: ela guarda quem está
desligado e, principalmente, **o valor que a conta tinha antes**, que é o
que o religar restaura. Sem a linha aqui, não há como religar direito —
só chutando, e chutar deixaria a conta com uma supervisão que ela nunca
teve.

Por isso a linha é gravada ANTES do PUT que desliga, e não depois: se o
processo morrer no meio, sobra uma linha dizendo "esta conta deveria
estar desligada" — que se confere — em vez de uma conta desligada que
ninguém sabe que existe.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db


class AvisoArmeDesligado(db.Model):
    """Uma conta que está (ou esteve) com o aviso de arme desligado."""

    __tablename__ = "aviso_arme_desligados"

    id = db.Column(db.Integer, primary_key=True)

    cue_iid = db.Column(db.String(16), nullable=False, index=True)
    conta = db.Column(db.String(16), nullable=False, default="")
    nome = db.Column(db.String(200), nullable=False, default="")

    # O valor de `tol_nnyc` que a conta tinha antes de ser desligada. É o
    # dado mais importante da tabela: é ele que o religar restaura.
    nnyc_original = db.Column(db.Integer, nullable=False)

    desligado_em = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    desligado_por_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    religado_em = db.Column(db.DateTime(timezone=True))
    religado_por_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    # Linha viva = conta desligada agora. A linha religada fica no banco
    # como histórico de quando cada loja ficou sem o aviso.
    ativo = db.Column(db.Boolean, nullable=False, default=True, index=True)

    def dias_desligado(self, agora: datetime | None = None) -> int:
        """Há quantos dias esta conta está sem o aviso.

        A tela usa isto para destacar o que passou de uma semana: sem
        expiração automática, "desligada há 23 dias" é o único sintoma de
        que alguém deixou de rodar a lista."""
        referencia = agora or datetime.now(timezone.utc)
        inicio = self.desligado_em
        if inicio.tzinfo is None:
            inicio = inicio.replace(tzinfo=timezone.utc)
        return max(0, (referencia - inicio).days)

    def __repr__(self) -> str:  # pragma: no cover - diagnóstico
        estado = "desligada" if self.ativo else "religada"
        return f"<AvisoArmeDesligado {self.conta} {estado}>"
