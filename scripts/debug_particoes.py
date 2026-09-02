"""Diagnóstico: confere como as PARTIÇÕES vêm do portal.

O bot passou a listar partições (`/clientes`, `/zona 95/2`) assumindo que,
sem o recorte `cue_nparticion = 0`, o `CuentaByDealer` devolve uma linha
por partição — mesmo `cue_ncuenta`, `cue_iid` próprio. Isso **não foi
validado contra o portal real**; este script mostra o que vem de verdade.

Uso (CMD, venv ativado, na pasta do projeto):
  python scripts\\debug_particoes.py [conta]

  [conta] = opcional, número da conta para detalhar (ex.: 43)

Ele compara as duas consultas (com e sem o filtro) e despeja **cru** o
que só aparece sem o filtro — sem supor nada sobre o formato. A primeira
execução em produção mostrou que a suposição original estava errada: as
188 linhas viraram 188 contas distintas, ou seja, as partições NÃO
compartilham o `cue_ncuenta` da conta principal.

O que olhar na saída:
  1. "O QUE SÃO ESSAS LINHAS A MAIS" -> os campos das linhas que o filtro
     escondia. É o que define como o bot deve identificar uma partição.
  2. "TODAS AS CHAVES" -> se o campo que liga a partição à conta mãe tiver
     outro nome, é aqui que ele aparece.
  3. A contagem final diz se dá para agrupar por `cue_ncuenta` ou se
     precisamos de outro vínculo.
"""

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.domain import contas as dom_contas  # noqa: E402
from app.services import collector  # noqa: E402
from app.integrations.softguard_client import (  # noqa: E402
    SoftGuardAuthError,
    SoftGuardClient,
)

CAMPOS_INTERESSANTES = ("cue_ncuenta", "cue_nparticion", "cue_iid", "cue_cnombre")


def main() -> None:
    alvo = sys.argv[1].strip().lstrip("0") if len(sys.argv) > 1 else ""

    app = create_app()
    with app.app_context():
        client = SoftGuardClient(collector.credenciais_softguard(app.config))

        try:
            so_principais = client.listar_todas_contas()
            com_particoes = client.listar_todas_contas(incluir_particoes=True)
        except SoftGuardAuthError as exc:
            print(
                f"\n>>> O LOGIN falhou (não chegou nas partições): {exc}\n\n"
                "    'Invalid Token' logo depois de um login que deu certo\n"
                "    normalmente é DISPUTA DE SESSÃO: o portal aceita uma\n"
                "    sessão por usuário, e o serviço PowerCentral (ou uma aba\n"
                "    do portal aberta no navegador) já está usando a mesma\n"
                "    conta de integração.\n\n"
                "    Tente assim, nesta ordem:\n"
                "      1. Stop-Service PowerCentral\n"
                "      2. feche o portal no navegador (se estiver aberto com\n"
                "         o mesmo usuário de integração)\n"
                "      3. rode este script de novo\n"
                "      4. Start-Service PowerCentral\n"
            )
            raise SystemExit(1)

        print(f"Linhas com o filtro atual (cue_nparticion=0): {len(so_principais)}")
        print(f"Linhas sem o filtro:                           {len(com_particoes)}")

        # Diferença por cue_iid: são exatamente as linhas que o filtro
        # `cue_nparticion = 0` escondia. Sem supor nada sobre o formato —
        # é isso que precisa ser olhado.
        ids_principais = {str(linha.get("cue_iid") or linha.get("Id")) for linha in so_principais}
        extras = [
            linha
            for linha in com_particoes
            if str(linha.get("cue_iid") or linha.get("Id")) not in ids_principais
        ]
        print(f"Linhas que só aparecem SEM o filtro:           {len(extras)}")

        if not extras:
            print(
                "\n>>> O filtro vazio não trouxe nada a mais. O portal deve\n"
                "    estar ignorando `filter=[]` — precisamos de outro filtro."
            )
            return

        print("\n=== O QUE SÃO ESSAS LINHAS A MAIS (amostra de 5) ===")
        for linha in extras[:5]:
            print({campo: linha.get(campo) for campo in CAMPOS_INTERESSANTES})

        print("\n=== TODAS AS CHAVES de uma dessas linhas ===")
        print(sorted(extras[0].keys()))

        print("\n=== LINHA CRUA COMPLETA (a primeira) ===")
        for chave, valor in sorted(extras[0].items()):
            print(f"  {chave} = {valor!r}")

        # A pergunta que decide o desenho: dá para ligar a partição à conta
        # "mãe"? Se o número da partição for diferente do da principal, o
        # agrupamento por número não serve.
        numeros_principais = {
            str(linha.get("cue_ncuenta", "")).strip().lstrip("0") for linha in so_principais
        }
        extras_com_numero_conhecido = [
            linha
            for linha in extras
            if str(linha.get("cue_ncuenta", "")).strip().lstrip("0") in numeros_principais
        ]
        print(
            f"\nDessas {len(extras)} linhas, {len(extras_com_numero_conhecido)} têm o mesmo\n"
            "cue_ncuenta de uma conta principal (ou seja: dá para agrupar por número)."
        )

        if alvo:
            print(f"\n=== TODAS as linhas com cue_ncuenta {alvo} ===")
            for linha in com_particoes:
                if str(linha.get("cue_ncuenta", "")).strip().lstrip("0") == alvo:
                    print({campo: linha.get(campo) for campo in CAMPOS_INTERESSANTES})


if __name__ == "__main__":
    main()
