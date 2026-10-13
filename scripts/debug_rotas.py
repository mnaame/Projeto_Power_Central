"""Mostra de onde a coordenada de cada cliente base vem — ou por que não vem.

Contexto: a primeira rodada em produção devolveu "105 clientes base, 0 com
coordenada, 0 Auvo · 0 Power". Zero absoluto, sem um erro na tela. A causa
foi nome de campo chutado: o código procurava a localização da conta em
`cue_clocalizacion`, que não é o nome do campo. Nenhum log acusava, porque
"campo ausente" e "campo vazio" são a mesma coisa para um `.get()`.

Agora `dom.coordenada_do_registro` reconhece a coordenada pela FORMA (dois
decimais dentro da caixa de MG/BH), não pelo nome. Este script é a prova
contra as plataformas de verdade: imprime os nomes de campo que cada lado
realmente devolve, quantas coordenadas aparecem em cada etapa e, no fim, a
lista de quem ficou sem — que é a fila de trabalho do cadastro.

Só leitura: nada é escrito na PowerCentral nem na Auvo.

Uso (PowerShell, na pasta do projeto):

  .venv\\Scripts\\python.exe scripts\\debug_rotas.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.domain import disparos_geral as dom_disp  # noqa: E402
from app.domain import rotas as dom  # noqa: E402
from app.integrations.softguard_client import SoftGuardClient  # noqa: E402
from app.services import auvo_service, rotas_service  # noqa: E402
from app.services.collector import credenciais_softguard  # noqa: E402

LIMITE_LISTA = 40


def _campos(registros, quantos=3):
    """Nomes de campo que a plataforma devolve de verdade — é o dado que
    faltava quando o módulo saiu chutando nome."""
    nomes = []
    for registro in registros[:quantos]:
        if isinstance(registro, dict):
            for chave in registro:
                if chave not in nomes:
                    nomes.append(chave)
    return nomes


def main() -> int:
    app = create_app()
    with app.app_context():
        print("== PowerCentral ==")
        client = SoftGuardClient(credenciais_softguard(app.config))
        contas = client.listar_todas_contas()
        print(f"{len(contas)} conta(s) no dealer")
        print("campos:", ", ".join(_campos(contas)))

        base = rotas_service._contas_base(contas)
        print(f"{len(base)} base (fora Villefort/Super Nosso/Apoio/interna)")

        com_power = [c for c in base if dom.coordenada_do_registro(c) is not None]
        print(f"{len(com_power)} com coordenada válida no cadastro da Power")

        print("\n== Auvo ==")
        auvo = auvo_service.criar_cliente(app.config)
        if auvo is None:
            print("Auvo não configurada (sem chave/token em Configurações).")
            clientes = []
        else:
            clientes = auvo.listar_clientes()
            print(f"{len(clientes)} cliente(s)")
            print("campos:", ", ".join(_campos(clientes)))
            com_auvo = [c for c in clientes if dom.coordenada_do_registro(c) is not None]
            print(f"{len(com_auvo)} com lat/long dentro da caixa de MG/BH")

        print("\n== Casamento ==")
        depara = rotas_service._depara_por_conta()
        por_id = rotas_service._mapa_auvo_por_id(clientes)
        nomes = {
            dom.normalizar(str(rotas_service._primeiro(c, rotas_service.CAMPOS_NOME_AUVO))): c
            for c in clientes
        }
        print(f"{len(depara)} linha(s) de de-para com status OK")

        por_depara = por_nome = de_auvo = da_power = 0
        sem = []
        for linha in base:
            conta = str(linha.get("cue_ncuenta") or "").strip()
            nome = str(linha.get("cue_cnombre") or "").strip()

            cliente = por_id.get(depara.get(conta.lstrip("0"), ""))
            if cliente is not None:
                por_depara += 1
            elif nomes:
                casado = dom.melhor_nome(nome, list(nomes))
                cliente = nomes.get(casado) if casado else None
                if cliente is not None:
                    por_nome += 1

            if cliente is not None and dom.coordenada_do_registro(cliente) is not None:
                de_auvo += 1
                continue
            if dom.coordenada_do_registro(linha) is not None:
                da_power += 1
                continue
            sem.append((conta, nome, cliente is not None))

        print(f"casaram pelo de-para: {por_depara}")
        print(f"casaram por nome:     {por_nome}")
        print(f"\ncoordenada da Auvo:   {de_auvo}")
        print(f"coordenada da Power:  {da_power}")
        print(f"sem coordenada:       {len(sem)}")

        if sem:
            print("\n-- fila de trabalho do cadastro --")
            for conta, nome, casou in sem[:LIMITE_LISTA]:
                onde = (
                    "está na Auvo, mas sem lat/long lá"
                    if casou
                    else "não casou com nenhum cliente da Auvo"
                )
                print(f"  {conta:>6}  {nome[:44]:<44} {onde}")
            if len(sem) > LIMITE_LISTA:
                print(f"  ... e mais {len(sem) - LIMITE_LISTA}")

        # Grupos, só para conferir que o recorte de "base" está certo —
        # uma conta classificada errado some da lista sem aviso.
        print("\n== Conferência do recorte ==")
        contagem: dict[str, int] = {}
        for conta in contas:
            nome = str(conta.get("cue_cnombre") or "").strip()
            if not nome:
                continue
            rotulo = "interna" if dom.e_interno(nome) else dom_disp.grupo_do_cliente(nome)
            contagem[rotulo] = contagem.get(rotulo, 0) + 1
        for rotulo, quantidade in sorted(contagem.items(), key=lambda kv: -kv[1]):
            print(f"  {rotulo}: {quantidade}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
