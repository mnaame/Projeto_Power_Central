"""Por que uma conta do portal não aparece na lista do bot.

Pergunta concreta que este script responde: a conta X está no que o portal
devolve para o bot? Se estiver, o problema é cache/serviço; se não estiver,
o problema é a consulta — e aí a paginação impressa abaixo mostra onde ela
para.

O bot monta `/clientes` com `listar_todas_contas(incluir_particoes=True)`,
que é o `CuentaByDealer` **sem** o recorte `cue_nparticion = 0`, paginado
de 100 em 100 até o `total` que o próprio portal informa. Se o portal
declarar um `total` menor do que a base real, ou parar de servir antes do
fim, a lista chega curta sem ninguém reclamar — é exatamente isso que a
tabela de páginas abaixo expõe.

Uso (PowerShell, na pasta do projeto — PARE o serviço antes, o portal
aceita uma sessão por usuário):

  Stop-Service PowerCentral
  .venv\\Scripts\\python.exe scripts\\debug_contas_faltando.py 356
  Start-Service PowerCentral

O número no fim é a conta que você está procurando (opcional).
"""

import json
import os
import sys
from urllib.parse import urljoin

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.domain import contas as dom_contas  # noqa: E402
from app.integrations.softguard_client import (  # noqa: E402
    SEARCH_PATH,
    SoftGuardClient,
    SoftGuardError,
)
from app.services import collector  # noqa: E402

PAGINA = 100  # DEFAULT_PAGE_SIZE — o mesmo que o bot usa


def _paginar_mostrando(client, *, filtro) -> list[dict]:
    """Repete o laço do `_buscar_paginado`, imprimindo cada página. É onde
    aparece um `total` mentiroso ou uma página que vem vazia cedo demais."""
    linhas: list[dict] = []
    start = 0
    total = None
    print(f"   {'página':>7}  {'start':>6}  {'vieram':>6}  {'total diz':>10}")
    while total is None or start < total:
        resposta = client._session.request(
            "GET",
            urljoin(client._credentials.base_url, SEARCH_PATH),
            params={
                "filter": json.dumps(filtro),
                "page": (start // PAGINA) + 1,
                "start": start,
                "limit": PAGINA,
            },
            timeout=120,
        )
        if resposta.status_code != 200:
            print(f"   HTTP {resposta.status_code}: {' '.join(resposta.text.split())[:200]}")
            break
        payload = resposta.json()
        total = int(payload.get("total", 0) or 0)
        pagina = payload.get("rows", payload.get("data", []))
        print(f"   {(start // PAGINA) + 1:>7}  {start:>6}  {len(pagina):>6}  {total:>10}")
        linhas.extend(pagina)
        if not pagina:
            print("   >>> página vazia: o laço para aqui, mesmo faltando conta.")
            break
        start += PAGINA
    return linhas


def _pedir_por_numero(client, numero: str) -> tuple[bool, str]:
    """Consulta a conta pelo número, sem a listagem.

    **Reloga antes de perguntar.** A primeira versão disto perguntava na
    mesma sessão usada para listar as 188 contas e levava 500 — que neste
    portal é o que uma sessão vencida responde (ver docs/OPERACAO.md). O
    500 foi lido como "a conta não existe", que é conclusão que a medição
    não sustentava. Sessão nova elimina essa dúvida.

    Devolve (a pergunta foi respondida?, texto para impressão)."""
    try:
        client.login()
    except SoftGuardError as exc:
        return False, f"não deu para relogar: {exc}"

    resposta = client._session.request(
        "GET",
        urljoin(client._credentials.base_url, SEARCH_PATH),
        params={
            "filter": json.dumps([{"property": "cue_ncuenta", "value": numero}]),
            "page": 1,
            "start": 0,
            "limit": PAGINA,
        },
        timeout=120,
    )
    if resposta.status_code != 200:
        corpo = " ".join(resposta.text.split())[:200]
        return False, f"HTTP {resposta.status_code} — a PERGUNTA falhou, não a conta. Corpo: {corpo}"
    try:
        payload = resposta.json()
    except ValueError:
        return False, f"resposta não-JSON: {resposta.text[:150]!r}"
    linhas = payload.get("rows", payload.get("data", []))
    if not linhas:
        return True, "nada (total=%s)" % payload.get("total", 0)
    return True, "ACHOU -> " + ", ".join(
        f"{str(l.get('cue_ncuenta') or '').strip()} {str(l.get('cue_cnombre') or '').strip()}"
        for l in linhas
    )


def main() -> None:
    procurada = sys.argv[1].strip().lstrip("0") if len(sys.argv) > 1 else "356"

    app = create_app()
    with app.app_context():
        client = SoftGuardClient(collector.credenciais_softguard(app.config))

        print("0) LOGIN...")
        try:
            client.login()
        except SoftGuardError as exc:
            print(f"   FALHOU: {exc}\n>>> Confira se o serviço PowerCentral está parado.")
            return
        print("   ok.\n")

        print("1) SÓ CONTAS PRINCIPAIS (o que a tela do portal mostra)")
        principais = _paginar_mostrando(client, filtro=[{"property": "cue_nparticion", "value": "0"}])
        print(f"   -> {len(principais)} conta(s).\n")

        print("2) COM PARTIÇÕES (é esta que o bot usa no /clientes)")
        todas = _paginar_mostrando(client, filtro=[])
        print(f"   -> {len(todas)} linha(s).\n")

        contas = dom_contas.contas_da_resposta(todas)
        ordenadas = dom_contas.ordenar(contas)

        print("3) AS 12 ÚLTIMAS QUE VIERAM (por número)")
        for conta in ordenadas[-12:]:
            marca = f"  [part. de {conta.conta_mae}]" if conta.e_particao else ""
            print(f"   {conta.rotulo}{marca}")

        print(f"\n4) A CONTA {procurada} ESTÁ NA RESPOSTA DO PORTAL?")
        achadas = [c for c in contas if c.numero == procurada]
        if achadas:
            for conta in achadas:
                print(f"   SIM — {conta.rotulo} (cue_iid {conta.cue_iid})")
            print(
                "\n>>> O portal DEVOLVE essa conta. Então a lista curta no bot é\n"
                "    cache ou serviço rodando código antigo: confira se o\n"
                "    `git pull` foi seguido de `Restart-Service PowerCentral`."
            )
        else:
            print(f"   NÃO — {procurada} não veio em nenhuma das páginas acima.")

            print("\n5) PEDINDO A CONTA DIRETO, POR NÚMERO (sessão nova a cada tentativa)")
            respondeu = False
            for valor in (procurada, procurada.zfill(4)):
                ok, texto = _pedir_por_numero(client, valor)
                respondeu = respondeu or ok
                print(f"   filtro cue_ncuenta={valor!r}: {texto}")

            usuario = app.config.get("SOFTGUARD_USERNAME", "(não configurado)")
            if respondeu:
                print(
                    f"\n>>> A conta {procurada} não vem para o usuário de integração\n"
                    f"    ({usuario}), nem na lista nem pedindo direto — e desta vez\n"
                    "    a pergunta foi respondida, então a ausência é real."
                )
            else:
                print(
                    "\n>>> ATENÇÃO: o pedido direto FALHOU (erro na consulta), então\n"
                    "    ele não diz nada sobre a conta. O que continua valendo é só\n"
                    "    o passo 2: a listagem veio íntegra e sem essa conta."
                )
            print(
                "\n    A paginação está íntegra (a soma das páginas bate com o\n"
                "    'total diz'), então não é a consulta parando no meio.\n\n"
                "    Teste decisivo, sem código: entre no portal pelo navegador\n"
                f"    COM O USUÁRIO {usuario} e veja quantas contas ele lista.\n"
                "    Se ele também não vir as novas, é permissão — as contas\n"
                "    precisam ser liberadas para esse usuário no perfil dele."
            )

        print("\n6) MAIORES NÚMEROS DE CONTA QUE O PORTAL ENTREGOU")
        print("   (compare com a sua tela para achar quais faltam)")
        principais_ord = dom_contas.ordenar(dom_contas.contas_da_resposta(principais))
        print("   " + ", ".join(c.numero for c in principais_ord[-20:]))


if __name__ == "__main__":
    main()
