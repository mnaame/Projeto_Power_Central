"""Diagnóstico: confere como as PARTIÇÕES vêm do portal.

O bot passou a listar partições (`/clientes`, `/zona 95/2`) assumindo que,
sem o recorte `cue_nparticion = 0`, o `CuentaByDealer` devolve uma linha
por partição — mesmo `cue_ncuenta`, `cue_iid` próprio. Isso **não foi
validado contra o portal real**; este script mostra o que vem de verdade.

Uso (CMD, venv ativado, na pasta do projeto):
  python scripts\\debug_particoes.py [conta]

  [conta] = opcional, número da conta para detalhar (ex.: 43)

O que olhar na saída:
  1. "com partições" > 0  -> a consulta sem filtro está trazendo os setores;
     se vier 0, o portal ignora o filtro vazio e precisamos de outro
     (ajustar `listar_todas_contas(incluir_particoes=True)`).
  2. Nos campos crus, confirmar que `cue_iid` MUDA entre as partições da
     mesma conta — é ele que o zoneamento e o export usam.
  3. Se o campo de partição tiver outro nome, ajustar `_particao` em
     `app/domain/contas.py`.
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
        print(f"Linhas sem o filtro (deve incluir partições):  {len(com_particoes)}")

        if len(com_particoes) <= len(so_principais):
            print(
                "\n>>> ATENÇÃO: a consulta sem filtro não trouxe linhas a mais.\n"
                "    O portal deve estar ignorando o filtro vazio — o bot vai\n"
                "    listar só as contas principais. Ajustar o filtro em\n"
                "    `listar_todas_contas(incluir_particoes=True)`."
            )

        contas = dom_contas.contas_da_resposta(com_particoes)
        agrupado = dom_contas.agrupar_por_numero(contas)
        multiplas = {n: p for n, p in agrupado.items() if dom_contas.tem_particoes(p)}

        print(f"\nContas distintas: {len(agrupado)}")
        print(f"Com partições:    {len(multiplas)}")
        print("Distribuição de partições por conta:",
              dict(Counter(len(p) for p in agrupado.values())))

        exemplos = list(multiplas.items())[:3]
        if alvo and alvo in agrupado:
            exemplos = [(alvo, agrupado[alvo])]

        if not exemplos:
            print("\nNenhuma conta com mais de uma linha — nada a detalhar.")
            return

        for numero, particoes in exemplos:
            print(f"\n--- Conta {numero} ({len(particoes)} linha(s)) ---")
            for conta in particoes:
                print(f"  particao={conta.particao}  cue_iid={conta.cue_iid}  {conta.nome}")
            ids = {c.cue_iid for c in particoes}
            if len(ids) < len(particoes):
                print(
                    "  >>> ATENÇÃO: cue_iid REPETIDO entre partições. O bot usa\n"
                    "      o cue_iid para consultar zoneamento/histórico, então\n"
                    "      escolher a partição não mudaria o resultado."
                )

        print("\n--- Campos crus da primeira conta com partições ---")
        numero = exemplos[0][0]
        for linha in com_particoes:
            if str(linha.get("cue_ncuenta", "")).strip().lstrip("0") == numero:
                print({campo: linha.get(campo) for campo in CAMPOS_INTERESSANTES})
        print("\nChaves disponíveis na linha:")
        for linha in com_particoes:
            if str(linha.get("cue_ncuenta", "")).strip().lstrip("0") == numero:
                print(sorted(linha.keys()))
                break


if __name__ == "__main__":
    main()
