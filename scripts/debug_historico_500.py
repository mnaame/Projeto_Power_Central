"""Diagnóstico: separa as três causas possíveis do 500 no ReporteHistorico.

A rodada anterior (`debug_historico_grande.py`) provou que **não são os
códigos**: `CLO` passou dentro de `[NYE,NYC,CLO,CLV,ROP]` e falhou sozinho
logo depois. O mesmo código não pode ser válido e inválido — então o que
mudou entre as duas chamadas foi outra coisa. Sobraram três hipóteses:

  A. ORDEM      — a 1ª consulta da sessão passa e as seguintes dão 500
                  (bate com produção: relatório grande = várias páginas de
                  100, e reiniciar o serviço "resolvia");
  B. VAZIO      — o portal explode quando a consulta não casa nenhuma linha;
  C. RITMO      — é limite de taxa: rápido demais dá 500, com pausa passa.

Cada teste abaixo isola uma delas, sempre com sessão nova quando a hipótese
exige. E toda falha imprime o CORPO da resposta — é onde o portal costuma
devolver o erro de verdade (SQL, stack), que o `SoftGuardError` engole.

> Armadilha registrada: `client._request()` **não faz login** — quem loga é
> o `_buscar_paginado`. Aqui o login é sempre explícito.

Uso (PowerShell, na pasta do projeto — PARE o serviço antes, o portal
aceita uma sessão por usuário):

  Stop-Service PowerCentral
  .venv\\Scripts\\python.exe scripts\\debug_historico_500.py
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
from app.services import collector, settings_service  # noqa: E402

FUSO = ZoneInfo("America/Sao_Paulo")
CODIGOS_DISPAROS = (dom_disp.CODIGO_DISPARO,) + dom_disp.CODIGOS_ARME + dom_disp.CODIGOS_DESARME
PAGINA = 100  # DEFAULT_PAGE_SIZE do client — o mesmo que produção usa


def _abrir_sessao(config, *, rotulo: str) -> SoftGuardClient | None:
    """Client novo (sessão HTTP nova) e já autenticado. `max_retries=1`
    porque um 500 aqui não é transitório e repetir só demora e martela o
    portal."""
    client = SoftGuardClient(collector.credenciais_softguard(config), max_retries=1)
    try:
        client.login()
    except SoftGuardError as exc:
        print(f"  !! login falhou em '{rotulo}': {exc}")
        return None
    return client


def _sondar(client: SoftGuardClient, *, codigos, desde, hasta, start=0, rotulo: str) -> int | None:
    """Chamada crua pela sessão do client (sem `_request`), para poder ler o
    corpo do erro. Devolve o `total` declarado, ou None se falhou."""
    resposta = client._session.request(
        "GET",
        urljoin(client._credentials.base_url, HISTORICO_PATH),
        params={
            "FechaDesde": desde.strftime(FORMATO_DATA_HISTORICO),
            "FechaHasta": hasta.strftime(FORMATO_DATA_HISTORICO),
            "CodigosAlarma": ",".join(codigos),
            "table": "p_recepcion",
            "OrdenarFecha": "DESC",
            "Mostrar": 5000,
            "page": (start // PAGINA) + 1,
            "start": start,
            "limit": PAGINA,
        },
        timeout=60,
    )
    if resposta.status_code != 200:
        corpo = " ".join(resposta.text.split())[:400]
        print(f"  FALHOU  {rotulo:<34} HTTP {resposta.status_code}")
        print(f"          corpo: {corpo or '(vazio)'}")
        return None
    try:
        payload = resposta.json()
    except ValueError:
        print(f"  FALHOU  {rotulo:<34} resposta não-JSON: {resposta.text[:200]!r}")
        return None
    total = int(payload.get("total", 0) or 0)
    linhas = payload.get("rows", payload.get("data", []))
    print(f"  ok      {rotulo:<34} total={total} linhas={len(linhas)}")
    return total


def _madrugada_de_domingo(agora: datetime) -> tuple[datetime, datetime]:
    """Janela de 10 min às 3h do domingo passado — quase certamente sem
    nenhum evento, para testar a hipótese do resultado vazio."""
    domingo = agora - timedelta(days=(agora.weekday() + 1) % 7 or 7)
    inicio = domingo.replace(hour=3, minute=0, second=0, microsecond=0)
    return inicio, inicio + timedelta(minutes=10)


def main() -> None:
    agora = datetime.now(FUSO)
    hasta = agora.replace(minute=0, second=0, microsecond=0)
    desde = hasta - timedelta(hours=3)

    app = create_app()
    with app.app_context():
        config = app.config
        controle = tuple(
            dict.fromkeys(
                (*settings_service.get_atend_codigos_evento(), *dom_disp.CODIGOS_ARME)
            )
        )
        print(f"Janela de teste: {desde:%d/%m %H:%M} -> {hasta:%d/%m %H:%M}")
        print(f"Controle: {','.join(controle)}\n")

        # ---- A: a 2ª consulta da mesma sessão sobrevive? -----------------
        print("A) MESMA sessão, a MESMA consulta três vezes seguidas:")
        client = _abrir_sessao(config, rotulo="A")
        if client is None:
            return
        primeira = _sondar(client, codigos=controle, desde=desde, hasta=hasta, rotulo="1ª vez")
        segunda = _sondar(client, codigos=controle, desde=desde, hasta=hasta, rotulo="2ª vez (imediata)")
        if primeira is not None and segunda is None:
            print("     ^ a 1ª passa e a 2ª não: é ESTADO DE SESSÃO, não os códigos.")
        time.sleep(20)
        terceira = _sondar(client, codigos=controle, desde=desde, hasta=hasta, rotulo="3ª vez (após 20s)")
        if segunda is None and terceira is not None:
            print("     ^ falhou rápido e passou com pausa: é RITMO (limite de taxa).")

        # ---- recuperação: re-login conserta? ------------------------------
        if segunda is None or terceira is None:
            print("\nA2) Depois da falha, faz login de novo e repete:")
            try:
                client.login()
                _sondar(client, codigos=controle, desde=desde, hasta=hasta, rotulo="após novo login")
            except SoftGuardError as exc:
                print(f"  !! novo login falhou: {exc}")

        # ---- B: e se a consulta não casar nada? ---------------------------
        print("\nB) Sessão NOVA, janela quase certamente vazia (3h de domingo):")
        vazio_desde, vazio_hasta = _madrugada_de_domingo(agora)
        client_b = _abrir_sessao(config, rotulo="B")
        if client_b is not None:
            _sondar(
                client_b,
                codigos=controle,
                desde=vazio_desde,
                hasta=vazio_hasta,
                rotulo=f"{vazio_desde:%d/%m %H:%M} +10min",
            )
            print("     ^ se falhou aqui sendo a 1ª da sessão, é RESULTADO VAZIO.")

        # ---- C: o código sozinho, como PRIMEIRA consulta da sessão --------
        print("\nC) Sessão NOVA para cada código — sempre a 1ª consulta da sessão:")
        for codigo in CODIGOS_DISPAROS:
            client_c = _abrir_sessao(config, rotulo=codigo)
            if client_c is None:
                continue
            _sondar(client_c, codigos=(codigo,), desde=desde, hasta=hasta, rotulo=f"[{codigo}] 1ª da sessão")
        print("     ^ se TODOS passam aqui, os códigos estão inocentes: o que")
        print("       derruba é a 2ª consulta em diante (ver A).")

        # ---- D: paginação, que é o caso real de produção ------------------
        print("\nD) Sessão NOVA, paginando os 7 códigos de 100 em 100 (como produção):")
        client_d = _abrir_sessao(config, rotulo="D")
        if client_d is not None:
            total = _sondar(
                client_d, codigos=CODIGOS_DISPAROS, desde=desde, hasta=hasta, rotulo="página 1 (start=0)"
            )
            if total:
                for start in range(PAGINA, min(total, 1000) + 1, PAGINA):
                    if _sondar(
                        client_d,
                        codigos=CODIGOS_DISPAROS,
                        desde=desde,
                        hasta=hasta,
                        start=start,
                        rotulo=f"start={start}",
                    ) is None:
                        print(f"     ^ quebrou na página {start // PAGINA + 1}. É ISSO que")
                        print("       derruba o relatório grande em produção.")
                        break


if __name__ == "__main__":
    main()
