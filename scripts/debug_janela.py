"""Descobre se o que derruba o ReporteHistorico é o TAMANHO DA JANELA.

O que já foi medido e está descartado:
  - os códigos (os 7 passam sozinhos);
  - o volume de páginas (1027 linhas em 11 páginas saem sem erro);
  - resultado vazio (janela sem evento responde normal);
  - token vencido — existe e foi corrigido no client, mas o erro de
    produção não traz "Invalid Token" no corpo, então há outra causa.

O que NUNCA foi testado: uma janela grande com **sessão nova**, pedindo só
a primeira página. Em produção o relatório que falha é de ~62h (~21 mil
linhas pela taxa medida) e falha logo de cara. Suspeito principal: o
`Mostrar=5000` que o client manda em toda chamada — se o portal tenta
materializar o resultado inteiro do lado dele, a janela grande explode
antes de paginar coisa alguma.

Por isso cada janela abre uma sessão NOVA e pede só `start=0`: isola o
tamanho da janela de tudo o mais. Na primeira que falhar, o script repete a
MESMA janela variando `Mostrar` — é o que separa "janela grande demais" de
"parâmetro errado".

Uso (PowerShell, na pasta do projeto — PARE o serviço antes, o portal
aceita uma sessão por usuário):

  Stop-Service PowerCentral
  .venv\\Scripts\\python.exe scripts\\debug_janela.py
  Start-Service PowerCentral
"""

import os
import sys
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.domain import disparos as dom_disp  # noqa: E402
from app.integrations.softguard_client import (  # noqa: E402
    FORMATO_DATA_HISTORICO,
    HISTORICO_PATH,
    SoftGuardClient,
    SoftGuardError,
)
from app.services import collector  # noqa: E402

FUSO = ZoneInfo("America/Sao_Paulo")
CODIGOS = (dom_disp.CODIGO_DISPARO,) + dom_disp.CODIGOS_ARME + dom_disp.CODIGOS_DESARME
# 62h é o tamanho do relatório que falha em produção (sex 18:00 -> seg 08:00).
JANELAS_HORAS = (3, 6, 12, 24, 36, 48, 62, 96)
MOSTRAR_ALTERNATIVOS = (1000, 500, 100, None)


def _pedir(client, *, desde, hasta, mostrar, limit=100):
    """Primeira página crua. Devolve (status, total, linhas, segundos, corpo)."""
    params = {
        "FechaDesde": desde.strftime(FORMATO_DATA_HISTORICO),
        "FechaHasta": hasta.strftime(FORMATO_DATA_HISTORICO),
        "CodigosAlarma": ",".join(CODIGOS),
        "table": "p_recepcion",
        "OrdenarFecha": "DESC",
        "page": 1,
        "start": 0,
        "limit": limit,
    }
    if mostrar is not None:
        params["Mostrar"] = mostrar

    inicio = time.monotonic()
    try:
        resposta = client._session.request(
            "GET",
            urljoin(client._credentials.base_url, HISTORICO_PATH),
            params=params,
            timeout=300,
        )
    except Exception as exc:  # timeout de rede também é resultado
        return None, None, None, time.monotonic() - inicio, f"{type(exc).__name__}: {exc}"

    gasto = time.monotonic() - inicio
    if resposta.status_code != 200:
        return resposta.status_code, None, None, gasto, " ".join(resposta.text.split())[:300]
    try:
        payload = resposta.json()
    except ValueError:
        return 200, None, None, gasto, f"não-JSON: {resposta.text[:200]!r}"
    total = int(payload.get("total", 0) or 0)
    linhas = len(payload.get("rows", payload.get("data", [])))
    return 200, total, linhas, gasto, ""


def _sessao(config, rotulo):
    client = SoftGuardClient(collector.credenciais_softguard(config), max_retries=1)
    try:
        client.login()
        return client
    except SoftGuardError as exc:
        print(f"  !! login falhou ({rotulo}): {exc}")
        return None


def main() -> None:
    hasta = datetime.now(FUSO).replace(minute=0, second=0, microsecond=0)

    app = create_app()
    with app.app_context():
        config = app.config
        print(f"Fim da janela: {hasta:%d/%m %H:%M} | códigos: {','.join(CODIGOS)}")
        print("Cada linha abre uma sessão NOVA e pede só a 1ª página.\n")
        print(f"{'janela':>7}  {'http':>4}  {'total':>7}  {'linhas':>6}  {'seg':>6}  detalhe")

        primeira_falha = None
        for horas in JANELAS_HORAS:
            client = _sessao(config, f"{horas}h")
            if client is None:
                continue
            desde = hasta - timedelta(hours=horas)
            status, total, linhas, gasto, corpo = _pedir(
                client, desde=desde, hasta=hasta, mostrar=5000
            )
            marca = status if status is not None else "ERR"
            print(
                f"{horas:>6}h  {marca:>4}  {total if total is not None else '—':>7}  "
                f"{linhas if linhas is not None else '—':>6}  {gasto:>6.1f}  {corpo}"
            )
            if status != 200 and primeira_falha is None:
                primeira_falha = (horas, desde)

        if primeira_falha is None:
            print(
                "\n>>> TODAS as janelas passaram na 1ª página, até 96h.\n"
                "    Então não é o tamanho da janela: o que quebra é o meio da\n"
                "    paginação (token vencendo), e aí o conserto que já subiu\n"
                "    resolve — confira se o serviço foi REINICIADO após o pull."
            )
            return

        horas, desde = primeira_falha
        print(f"\nPrimeira janela que falhou: {horas}h. Repetindo com outros `Mostrar`:")
        print(f"{'Mostrar':>8}  {'http':>4}  {'total':>7}  {'linhas':>6}  {'seg':>6}  detalhe")
        for mostrar in MOSTRAR_ALTERNATIVOS:
            client = _sessao(config, f"mostrar={mostrar}")
            if client is None:
                continue
            status, total, linhas, gasto, corpo = _pedir(
                client, desde=desde, hasta=hasta, mostrar=mostrar
            )
            marca = status if status is not None else "ERR"
            rotulo = "(sem)" if mostrar is None else mostrar
            print(
                f"{rotulo:>8}  {marca:>4}  {total if total is not None else '—':>7}  "
                f"{linhas if linhas is not None else '—':>6}  {gasto:>6.1f}  {corpo}"
            )

        print(
            "\n>>> Se algum `Mostrar` menor passou na MESMA janela, o culpado é\n"
            "    esse parâmetro e o conserto é trocar o valor fixo de 5000.\n"
            "    Se todos falharam, o limite é a janela mesmo, e o conserto é\n"
            "    fatiar a busca em pedaços do tamanho da maior que passou."
        )


if __name__ == "__main__":
    main()
