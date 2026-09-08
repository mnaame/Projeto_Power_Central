"""Diagnóstico: por que o ReporteHistorico devolve 500 num período grande.

Sintoma em produção (08/09/2026): o relatório de Disparos Geral falhou em
dois períodos de 3 e 4 dias com `500 Server Error` vindo do próprio portal
— inclusive na janela padrão de fim de semana (sexta 18h → segunda 08h).
O de Atendimentos, no mesmo horário, passou; ele consulta códigos de
volume muito menor.

A suspeita é VOLUME, e este script mede em vez de supor. Ele:

  1. pede a MESMA janela que falhou e mostra o erro;
  2. vai reduzindo a janela (4d, 3d, 2d, 1d, 12h, 6h, 3h) e diz onde
     começa a passar;
  3. em cada tentativa mostra o `total` que o portal declara e quantas
     linhas realmente vieram — é isso que testa a outra hipótese: o
     `Mostrar=5000` que o client envia. Se o portal declara total acima
     de 5000 e quebra ao paginar além disso, o conserto é fatiar a busca
     por tempo, não mexer no tamanho da página.

Uso (PowerShell, na pasta do projeto — PARE o serviço antes, o portal
aceita uma sessão por usuário):

  Stop-Service PowerCentral
  .venv\\Scripts\\python.exe scripts\\debug_historico_grande.py
  Start-Service PowerCentral

Opcional, para repetir um período exato:
  .venv\\Scripts\\python.exe scripts\\debug_historico_grande.py 2026-09-04T18:00 2026-09-08T08:00
"""

import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.domain import disparos as dom_disp  # noqa: E402
from app.integrations.softguard_client import (  # noqa: E402
    HISTORICO_PATH,
    SoftGuardClient,
    SoftGuardError,
)
from app.services import collector  # noqa: E402

FUSO = ZoneInfo("America/Sao_Paulo")
CODIGOS = (dom_disp.CODIGO_DISPARO,) + dom_disp.CODIGOS_ARME + dom_disp.CODIGOS_DESARME
JANELAS_HORAS = (96, 72, 48, 24, 12, 6, 3)


def _parse(texto: str) -> datetime:
    for formato in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, formato).replace(tzinfo=FUSO)
        except ValueError:
            continue
    raise SystemExit(f"Data inválida: {texto!r} — use 2026-09-04T18:00")


def _uma_pagina(client: SoftGuardClient, *, desde, hasta, start: int, limit: int) -> dict:
    """Uma página crua, sem o loop de paginação — para ver o `total` que o
    portal declara e em que ponto ele quebra."""
    from urllib.parse import urljoin

    from app.integrations.softguard_client import FORMATO_DATA_HISTORICO

    resposta = client._request(
        "GET",
        urljoin(client._credentials.base_url, HISTORICO_PATH),
        params={
            "FechaDesde": desde.strftime(FORMATO_DATA_HISTORICO),
            "FechaHasta": hasta.strftime(FORMATO_DATA_HISTORICO),
            "CodigosAlarma": ",".join(CODIGOS),
            "table": "p_recepcion",
            "OrdenarFecha": "DESC",
            "Mostrar": 5000,
            "page": (start // limit) + 1,
            "start": start,
            "limit": limit,
        },
    )
    return client._json(resposta)


def _sondar(client: SoftGuardClient, *, desde, hasta, rotulo: str) -> None:
    print(f"\n--- {rotulo}: {desde:%d/%m %H:%M} -> {hasta:%d/%m %H:%M} ---")
    try:
        payload = _uma_pagina(client, desde=desde, hasta=hasta, start=0, limit=100)
    except SoftGuardError as exc:
        print(f"  1ª página JÁ FALHOU: {str(exc)[:160]}")
        return

    total = int(payload.get("total", 0) or 0)
    linhas = payload.get("rows", payload.get("data", []))
    print(f"  1ª página OK — total declarado: {total} | linhas nesta página: {len(linhas)}")

    if total > 5000:
        print(
            "  >>> total ACIMA de 5000, que é o `Mostrar` enviado pelo client.\n"
            "      Se a paginação quebrar além disso, é aqui que está a causa."
        )

    # Onde a paginação quebra? Anda de 1000 em 1000 até o total declarado.
    for start in range(1000, min(total, 20000) + 1, 1000):
        try:
            pagina = _uma_pagina(client, desde=desde, hasta=hasta, start=start, limit=100)
        except SoftGuardError as exc:
            print(f"  QUEBROU em start={start}: {str(exc)[:120]}")
            return
        vieram = len(pagina.get("rows", pagina.get("data", [])))
        if vieram == 0:
            print(f"  start={start}: 0 linhas (portal parou de servir antes do total)")
            return
    print(f"  paginação foi até o fim sem erro (total {total})")


def main() -> None:
    if len(sys.argv) >= 3:
        hasta = _parse(sys.argv[2])
        desde = _parse(sys.argv[1])
    else:
        # Reproduz a janela padrão de fim de semana que falhou.
        hasta = datetime.now(FUSO).replace(minute=0, second=0, microsecond=0)
        desde = hasta - timedelta(hours=JANELAS_HORAS[0])

    app = create_app()
    with app.app_context():
        client = SoftGuardClient(collector.credenciais_softguard(app.config))
        print(f"Códigos consultados: {','.join(CODIGOS)}")

        _sondar(client, desde=desde, hasta=hasta, rotulo="janela pedida")

        for horas in JANELAS_HORAS:
            if hasta - timedelta(hours=horas) <= desde:
                continue
            _sondar(
                client,
                desde=hasta - timedelta(hours=horas),
                hasta=hasta,
                rotulo=f"últimas {horas}h",
            )

        print(
            "\nLeitura: a maior janela que passa ponta a ponta é o tamanho\n"
            "seguro para fatiar a busca. Se TODAS falharem, não é volume —\n"
            "me mande a saída que eu investigo por outro caminho."
        )


if __name__ == "__main__":
    main()
