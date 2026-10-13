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
