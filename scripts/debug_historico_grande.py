"""Diagnóstico: por que o ReporteHistorico devolve 500.

Histórico deste script: a primeira versão testou se o problema era o
TAMANHO da janela. Rodou em produção (08/09/2026) e **descartou volume** —
falhou igual em 96h e em 3h, sempre na primeira página. Então não é
paginação nem `Mostrar=5000`.

O que sobra: a própria consulta. E há uma pista forte — o relatório de
Atendimentos passou no mesmo dia, usando a MESMA função, com os MESMOS
parâmetros fixos (`table`, `OrdenarFecha`, `Mostrar`, formato de data).
A única diferença é a lista de `CodigosAlarma`.

Este script isola isso: mesma janela curta para todos os testes, mudando
só os códigos.

  1. controle com os códigos do Atendimentos (deve PASSAR);
  2. os 7 códigos do Disparos juntos (deve FALHAR);
  3. um código por vez — se um deles quebra sozinho, achamos o culpado;
  4. se todos passarem sozinhos, vai somando até quebrar (aí o problema é
     a combinação ou o tamanho da lista, não um código específico).

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
# Janela curta de propósito: já sabemos que tamanho não é o problema.
JANELA_HORAS = 3


def _consultar(client: SoftGuardClient, *, codigos, desde, hasta) -> dict:
    """Uma página crua, sem o loop de paginação."""
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
            "page": 1,
            "start": 0,
            "limit": 100,
        },
    )
    return client._json(resposta)


def _testar(client, *, codigos, desde, hasta, rotulo: str) -> bool:
    etiqueta = ",".join(codigos) if codigos else "(vazio)"
    try:
        payload = _consultar(client, codigos=codigos, desde=desde, hasta=hasta)
    except SoftGuardError as exc:
        curto = str(exc).split(" for url")[0][-90:]
        print(f"  FALHOU  {rotulo:<22} [{etiqueta}]  {curto}")
        return False
    total = int(payload.get("total", 0) or 0)
    linhas = payload.get("rows", payload.get("data", []))
    print(f"  ok      {rotulo:<22} [{etiqueta}]  total={total} linhas={len(linhas)}")
    return True


def main() -> None:
    hasta = datetime.now(FUSO).replace(minute=0, second=0, microsecond=0)
    desde = hasta - timedelta(hours=JANELA_HORAS)

    app = create_app()
    with app.app_context():
        client = SoftGuardClient(collector.credenciais_softguard(app.config))
        codigos_atendimentos = tuple(
            dict.fromkeys(
                (*settings_service.get_atend_codigos_evento(), *dom_disp.CODIGOS_ARME)
            )
        )

        print(f"Janela fixa: {desde:%d/%m %H:%M} -> {hasta:%d/%m %H:%M} ({JANELA_HORAS}h)")
        print("(tamanho já foi descartado — aqui só muda a lista de códigos)\n")

        print("1) CONTROLE — códigos do Atendimentos, que passou hoje:")
        controle_ok = _testar(
            client, codigos=codigos_atendimentos, desde=desde, hasta=hasta,
            rotulo="atendimentos",
        )
        if not controle_ok:
            print(
                "\n>>> Até o CONTROLE falhou. Então não são os códigos: ou o\n"
                "    endpoint está fora, ou o usuário de integração perdeu\n"
                "    permissão nele. Me mande esta saída."
            )
            return

        print("\n2) Os 7 códigos do Disparos juntos:")
        if _testar(
            client, codigos=CODIGOS_DISPAROS, desde=desde, hasta=hasta, rotulo="disparos (todos)"
        ):
            print(
                "\n>>> Passou agora! Então o 500 de hoje foi momentâneo (portal\n"
                "    instável), não um defeito da consulta. Tente o relatório\n"
                "    de novo pela tela."
            )
            return

        print("\n3) Um código por vez — quem quebra sozinho:")
        individuais = {c: _testar(
            client, codigos=(c,), desde=desde, hasta=hasta, rotulo=f"só {c}"
        ) for c in CODIGOS_DISPAROS}

        culpados = [c for c, ok in individuais.items() if not ok]
        if culpados:
            print(
                f"\n>>> CULPADO(S): {', '.join(culpados)}\n"
                "    Esse(s) código(s) derruba(m) o endpoint sozinho(s). O\n"
                "    conserto é no que o sistema pede, não no tamanho."
            )
            return

        print("\n4) Todos passam sozinhos — somando até quebrar:")
        acumulado: list[str] = []
        for codigo in CODIGOS_DISPAROS:
            acumulado.append(codigo)
            if not _testar(
                client, codigos=tuple(acumulado), desde=desde, hasta=hasta,
                rotulo=f"{len(acumulado)} código(s)",
            ):
                print(
                    f"\n>>> Quebra ao incluir **{codigo}** junto dos anteriores.\n"
                    "    Não é o código sozinho, é a combinação/quantidade —\n"
                    "    o conserto é dividir a consulta por códigos."
                )
                return

        print(
            "\n>>> Tudo passou agora, inclusive os 7 juntos. O 500 de hoje foi\n"
            "    momentâneo. Tente o relatório de novo pela tela."
        )


if __name__ == "__main__":
    main()
