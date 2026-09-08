"""Mede o maior `limit` que o ReporteHistorico honra de verdade.

Contexto: o client pagina de 100 em 100 (`DEFAULT_PAGE_SIZE`), então um
relatório de 4 dias vira ~330 requisições e vários minutos de portal. Já
sabemos que o token vence no meio disso — o client agora renova sozinho,
mas menos páginas continua sendo melhor: menos tempo, menos renovação,
menos chance de o navegador desistir antes.

O parâmetro `Mostrar=5000` já vai em toda chamada, mas quem governa o
tamanho da página é o `limit`. Este script descobre até onde o portal
obedece — e, principalmente, se ele **mente**: aceitar `limit=1000` e
devolver 100 calado seria pior que paginar, porque o laço de paginação
confia na contagem que volta.

Uso (PowerShell, na pasta do projeto — PARE o serviço antes):

  Stop-Service PowerCentral
  .venv\\Scripts\\python.exe scripts\\debug_page_size.py
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
TAMANHOS = (100, 250, 500, 1000, 2000, 5000)


def main() -> None:
    hasta = datetime.now(FUSO).replace(minute=0, second=0, microsecond=0)
    desde = hasta - timedelta(hours=6)  # janela com bastante linha (~2 mil)

    app = create_app()
    with app.app_context():
        client = SoftGuardClient(collector.credenciais_softguard(app.config), max_retries=1)
        try:
            client.login()
        except SoftGuardError as exc:
            print(f"login falhou: {exc}")
            return

        print(f"Janela: {desde:%d/%m %H:%M} -> {hasta:%d/%m %H:%M} (6h)")
        print(f"Códigos: {','.join(CODIGOS)}\n")
        print(f"{'limit':>6}  {'linhas':>7}  {'total':>7}  {'seg':>5}  observação")

        for limite in TAMANHOS:
            inicio = time.monotonic()
            resposta = client._session.request(
                "GET",
                urljoin(client._credentials.base_url, HISTORICO_PATH),
                params={
                    "FechaDesde": desde.strftime(FORMATO_DATA_HISTORICO),
                    "FechaHasta": hasta.strftime(FORMATO_DATA_HISTORICO),
                    "CodigosAlarma": ",".join(CODIGOS),
                    "table": "p_recepcion",
                    "OrdenarFecha": "DESC",
                    "Mostrar": 5000,
                    "page": 1,
                    "start": 0,
                    "limit": limite,
                },
                timeout=180,
            )
            gasto = time.monotonic() - inicio

            if resposta.status_code != 200:
                corpo = " ".join(resposta.text.split())[:200]
                print(f"{limite:>6}  {'—':>7}  {'—':>7}  {gasto:>5.1f}  HTTP {resposta.status_code}: {corpo}")
                continue
            try:
                payload = resposta.json()
            except ValueError:
                print(f"{limite:>6}  {'—':>7}  {'—':>7}  {gasto:>5.1f}  resposta não-JSON")
                continue

            total = int(payload.get("total", 0) or 0)
            linhas = len(payload.get("rows", payload.get("data", [])))
            if linhas >= min(limite, total):
                nota = "honrou"
            else:
                nota = f"IGNOROU (pediu {limite}, veio {linhas})"
            print(f"{limite:>6}  {linhas:>7}  {total:>7}  {gasto:>5.1f}  {nota}")

        print(
            "\nO maior `limit` marcado como 'honrou' é o que vale usar em\n"
            "DEFAULT_PAGE_SIZE. Se algum 'IGNOROU', o portal está capando a\n"
            "página em silêncio e o valor acima dele não serve."
        )


if __name__ == "__main__":
    main()
