"""Endereços importados das planilhas, para o catálogo por bairro.

Existe porque o catálogo não pode depender de adivinhar nome de campo de
API. A Auvo e a PowerCentral exportam, as duas, uma planilha com o
endereço de cada cliente — e essa planilha é um dado que a operação já
tem na mão e sabe gerar. Importar resolve hoje, sem depender de descobrir
como cada plataforma resolveu chamar o campo nesta versão.

Uma importação **substitui inteira** a fonte que ela traz: a planilha é
um retrato completo daquele lado, e misturar retrato novo com linha velha
deixaria no sistema um endereço que já não existe mais no cadastro, sem
ninguém notar.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db


class RotasEndereco(db.Model):
    """Um endereço de cliente vindo de planilha, já separado em partes."""

    __tablename__ = "rotas_enderecos"

    id = db.Column(db.Integer, primary_key=True)

    # De onde veio — e é por aqui que a reimportação apaga o lote antigo.
    fonte = db.Column(db.String(32), nullable=False, index=True)

    # As duas chaves possíveis de casamento. A conta vem da planilha da
    # PowerCentral, o id_auvo vem do "Código" da planilha da Auvo (o mesmo
    # id que o de-para guarda). Nome é a reserva das duas.
    conta_power = db.Column(db.String(16), index=True)
    id_auvo = db.Column(db.Integer, index=True)
    nome = db.Column(db.String(200), nullable=False, default="")
    nome_norm = db.Column(db.String(200), nullable=False, default="", index=True)

    bairro = db.Column(db.String(120), nullable=False, default="")
    cidade = db.Column(db.String(120), nullable=False, default="")
    uf = db.Column(db.String(2), nullable=False, default="")
    cep = db.Column(db.String(12), nullable=False, default="")
    # O endereço como estava na planilha, para conferir quando a leitura
    # sair estranha — sem isto, "bairro errado" não tem como ser apurado.
    endereco_bruto = db.Column(db.Text, nullable=False, default="")

    importado_em = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    importado_por_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    def __repr__(self) -> str:  # pragma: no cover - diagnóstico
        return f"<RotasEndereco {self.fonte} {self.conta_power or self.nome!r}>"


class RotasCiclo(db.Model):
    """Uma rodada de preventivas: o catálogo gerado e o que já foi visitado.

    O catálogo **precisa** morar no banco, e não na sessão do navegador.
    A versão anterior guardava o resultado no cookie de sessão: com a base
    real ele dava 4.746 bytes contra um limite de 4.093, o navegador
    descartava o cookie calado, e a tela respondia "nenhum catálogo gerado
    ainda" logo depois de gerar — sem erro nenhum, porque do ponto de
    vista do código a sessão só tinha vindo vazia.

    Guardar também é o que permite a rodada ter memória: o técnico visita
    ao longo de dias, e a marca do que já foi tem que sobreviver a fechar
    o navegador, a trocar de máquina e a gerar o catálogo de novo.
    """

    __tablename__ = "rotas_ciclos"

    id = db.Column(db.Integer, primary_key=True)
    # Numeração visível ("Ciclo #3"), para a equipe falar de uma rodada.
    numero = db.Column(db.Integer, nullable=False, default=1)
    iniciado_em = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    # Preenchido quando a rodada é reiniciada: marca o fim do ciclo.
    encerrado_em = db.Column(db.DateTime(timezone=True))
    atualizado_em = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    criado_por_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    # Contadores e diagnóstico da geração (de onde veio cada endereço,
    # erro da Auvo). É o que a tela mostra no resumo.
    resumo = db.Column(db.JSON, nullable=False, default=dict)

    clientes = db.relationship(
        "RotasCicloCliente",
        backref="ciclo",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - diagnóstico
        return f"<RotasCiclo #{self.numero}>"


class RotasCicloCliente(db.Model):
    """Um cliente base dentro de uma rodada, com a marca da visita."""

    __tablename__ = "rotas_ciclo_clientes"

    id = db.Column(db.Integer, primary_key=True)
    ciclo_id = db.Column(
        db.Integer, db.ForeignKey("rotas_ciclos.id"), nullable=False, index=True
    )

    conta = db.Column(db.String(16), nullable=False, index=True)
    nome = db.Column(db.String(200), nullable=False, default="")
    bairro = db.Column(db.String(120), nullable=False, default="")
    cidade = db.Column(db.String(120), nullable=False, default="")
    fonte = db.Column(db.String(32), nullable=False, default="")

    # Nulo = ainda não visitado. A data é o dado útil: "quando passamos
    # lá" responde mais que um booleano, e dá para auditar a rodada.
    visitado_em = db.Column(db.DateTime(timezone=True))
    visitado_por_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    @property
    def visitado(self) -> bool:
        return self.visitado_em is not None

    def __repr__(self) -> str:  # pragma: no cover - diagnóstico
        return f"<RotasCicloCliente {self.conta} {'ok' if self.visitado else '-'}>"
