"""Diagnóstico: por que o ReporteHistorico devolve 500.

> **Cuidado ao mexer aqui:** as duas primeiras versões deste script
> chamavam `client._request(...)` direto, e `_request` **não faz login** —
> quem loga é o `_buscar_paginado`. Resultado: as sondagens rodaram sem
> autenticação e o portal devolveu 500 em tudo, inclusive no controle.
> Duas rodadas inteiras foram jogadas fora por causa disso. Agora o login
> é explícito e conferido antes de qualquer medição.

O que o script mede, em UMA rodada:

  1. login (se falhar, para aqui e diz o porquê);
  2. controle: códigos do Atendimentos numa janela curta — é a consulta
     que sabidamente funciona pela tela;
  3. os 7 códigos do Disparos na mesma janela curta;
     - falhou? isola um código por vez, e depois somando;
     - passou? aumenta a janela (6h, 12h, 24h, 48h, 72h, 96h) até quebrar,
       mostrando o `total` declarado contra as linhas servidas — é o que
       testa o `Mostrar=5000` que o client envia.

Uso (PowerShell, na pasta do projeto — PARE o serviço antes, o portal
aceita uma sessão por usuário):

  Stop-Service PowerCentral
  .venv\\Scripts\\python.exe scripts\\debug_historico_grande.py
  Start-Service PowerCentral
"""

import os
import sys
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
from app.services import collector, settings_service  # noqa: E402

FUSO = ZoneInfo("America/Sao_Paulo")
CODIGOS_DISPAROS = (dom_disp.CODIGO_DISPARO,) + dom_disp.CODIGOS_ARME + dom_disp.CODIGOS_DESARME
JANELA_CURTA_HORAS = 3
JANELAS_CRESCENTES = (6, 12, 24, 48, 72, 96)


def _consultar(client: SoftGuardClient, *, codigos, desde, hasta, start=0, limit=100) -> dict:
    """Uma página crua. O login TEM que ter sido feito antes — `_request`
    não autentica sozinho (foi o que estragou as versões anteriores)."""
    resposta = client._request(
        "GET",
        urljoin(client._credentials.base_url, HISTORICO_PATH),
        params={
            "FechaDesde": desde.strftime(FORMATO_DATA_HISTORICO),
            "FechaHasta": hasta.strftime(FORMATO_DATA_HISTORICO),
            "CodigosAlarma": ",".join(codigos),
            "table": "p_recepcion",
            "OrdenarFecha": "DESC",
            "Mostrar": 5000,
            "page": (start // limit) + 1,
            "start": start,
            "limit": limit,
        },
    )
    return client._json(resposta)


def _testar(client, *, codigos, desde, hasta, rotulo: str) -> int | None:
    """Devolve o `total` declarado, ou None se falhou."""
    etiqueta = ",".join(codigos)
    try:
        payload = _consultar(client, codigos=codigos, desde=desde, hasta=hasta)
    except SoftGuardError as exc:
        curto = str(exc).split(" for url")[0][-80:]
        print(f"  FALHOU  {rotulo:<20} [{etiqueta}]  {curto}")
        return None
    total = int(payload.get("total", 0) or 0)
    linhas = payload.get("rows", payload.get("data", []))
    print(f"  ok      {rotulo:<20} [{etiqueta}]  total={total} linhas={len(linhas)}")
    return total


def _paginar_ate_quebrar(client, *, codigos, desde, hasta, total: int) -> None:
    """Anda de 1000 em 1000 para achar onde a paginação quebra — é o que
    testa o `Mostrar=5000`."""
    if total <= 100:
        return
    for start in range(1000, min(total, 20000) + 1, 1000):
        try:
            pagina = _consultar(client, codigos=codigos, desde=desde, hasta=hasta, start=start)
        except SoftGuardError as exc:
            print(f"    >>> paginação QUEBROU em start={start}: {str(exc)[:90]}")
            return
        vieram = len(pagina.get("rows", pagina.get("data", [])))
        if vieram == 0:
            print(f"    >>> portal parou de servir em start={start} (total dizia {total})")
            return
    print(f"    paginação foi até o fim sem erro (total {total})")


def main() -> None:
    hasta = datetime.now(FUSO).replace(minute=0, second=0, microsecond=0)
    desde = hasta - timedelta(hours=JANELA_CURTA_HORAS)

    app = create_app()
    with app.app_context():
        client = SoftGuardClient(collector.credenciais_softguard(app.config))

        print("0) LOGIN no portal...")
        try:
            client.login()
        except SoftGuardError as exc:
            print(
                f"   FALHOU: {exc}\n\n"
                ">>> Sem login não dá para medir nada. Se for 'Invalid Token',\n"
                "    é disputa de sessão: confira se o serviço PowerCentral\n"
                "    está mesmo parado e se o portal não está aberto no\n"
                "    navegador com o mesmo usuário de integração."
            )
            return
        print("   ok, autenticado.\n")

        codigos_atendimentos = tuple(
            dict.fromkeys(
                (*settings_service.get_atend_codigos_evento(), *dom_disp.CODIGOS_ARME)
            )
        )
        print(f"Janela curta: {desde:%d/%m %H:%M} -> {hasta:%d/%m %H:%M} ({JANELA_CURTA_HORAS}h)\n")

        print("1) CONTROLE — códigos do Atendimentos:")
        if _testar(
            client, codigos=codigos_atendimentos, desde=desde, hasta=hasta, rotulo="atendimentos"
        ) is None:
            print(
                "\n>>> O CONTROLE falhou mesmo autenticado. Então não são os\n"
                "    códigos nem o tamanho: ou o endpoint está fora, ou o\n"
                "    usuário de integração perdeu permissão nele.\n"
                "    Me mande esta saída."
            )
            return

        print("\n2) Os 7 códigos do Disparos, mesma janela curta:")
        total = _testar(
            client, codigos=CODIGOS_DISPAROS, desde=desde, hasta=hasta, rotulo="disparos"
        )

        if total is None:
            print("\n3) Um código por vez:")
            individuais = {
                c: _testar(client, codigos=(c,), desde=desde, hasta=hasta, rotulo=f"só {c}")
                for c in CODIGOS_DISPAROS
            }
            culpados = [c for c, t in individuais.items() if t is None]
            if culpados:
                print(f"\n>>> CULPADO(S): {', '.join(culpados)} — derruba(m) sozinho(s).")
                return

            print("\n4) Todos passam sozinhos — somando até quebrar:")
            acumulado: list[str] = []
            for codigo in CODIGOS_DISPAROS:
                acumulado.append(codigo)
                if _testar(
                    client, codigos=tuple(acumulado), desde=desde, hasta=hasta,
                    rotulo=f"{len(acumulado)} código(s)",
                ) is None:
                    print(f"\n>>> Quebra ao incluir {codigo} — é a combinação, não o código.")
                    return
            print("\n>>> Tudo passou agora. O 500 de hoje foi momentâneo.")
            return

        # Passou na janela curta: agora testa TAMANHO (a hipótese original,
        # que as rodadas sem login não chegaram a medir de verdade).
        _paginar_ate_quebrar(client, codigos=CODIGOS_DISPAROS, desde=desde, hasta=hasta, total=total)

        print("\n3) Aumentando a janela até quebrar:")
        for horas in JANELAS_CRESCENTES:
            inicio = hasta - timedelta(hours=horas)
            total = _testar(
                client, codigos=CODIGOS_DISPAROS, desde=inicio, hasta=hasta, rotulo=f"{horas}h"
            )
            if total is None:
                print(
                    f"\n>>> Quebra a partir de {horas}h. A maior janela que passou\n"
                    "    é o tamanho seguro para fatiar a busca."
                )
                return
            _paginar_ate_quebrar(
                client, codigos=CODIGOS_DISPAROS, desde=inicio, hasta=hasta, total=total
            )

        print(
            "\n>>> Passou em tudo, até 96h. Então o 500 de hoje foi momentâneo\n"
            "    (portal instável) — tente o relatório de novo pela tela."
        )


if __name__ == "__main__":
    main()
