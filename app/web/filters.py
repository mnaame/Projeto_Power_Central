from __future__ import annotations

from datetime import date, datetime, timezone

from app.domain.central_cliente import formatar_telefone_exibicao
from app.domain.dates import FUSO_HORARIO
from app.domain.formatting import formatar_duracao


def registrar_filtros(app) -> None:
    @app.template_filter("data_local")
    def data_local(valor: datetime | None) -> str:
        if valor is None:
            return "—"
        return valor.astimezone(FUSO_HORARIO).strftime("%d/%m/%Y %H:%M")

    @app.template_filter("data_curta")
    def data_curta(valor: date | None) -> str:
        if valor is None:
            return "—"
        return valor.strftime("%d/%m/%Y")

    @app.template_filter("duracao_ate_agora")
    def duracao_ate_agora(valor: datetime | None) -> str:
        if valor is None:
            return "—"
        return formatar_duracao(valor, datetime.now(timezone.utc))

    @app.template_filter("telefone_exibicao")
    def telefone_exibicao(valor: str | None) -> str:
        if not valor:
            return "—"
        return formatar_telefone_exibicao(valor)
