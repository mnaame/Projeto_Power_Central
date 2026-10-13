"""Mostra de onde vem o bairro de cada cliente base — ou por que não vem.

Contexto: este módulo já queimou duas rodadas em produção porque o código
procurava campo de API pelo nome que a gente *achava* que ele tinha. Na
primeira foi `cue_clocalizacion` para a coordenada; o resultado foi "105
clientes base, 0 com coordenada", zero absoluto e nenhum erro na tela,
porque para um `.get()` "campo com outro nome" e "campo vazio" são a
mesma coisa.

Este script existe para que ninguém precise adivinhar de novo: ele
imprime **os nomes de campo que cada plataforma devolve de verdade** e
quantos clientes sobrevivem a cada etapa. Só leitura — nada é escrito na
PowerCentral nem na Auvo.

Uso (PowerShell, na pasta do projeto):

  .venv\\Scripts\\python.exe scripts\\debug_rotas.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.domain import endereco as dom_end  # noqa: E402
from app.domain import rotas as dom  # noqa: E402
from app.integrations.softguard_client import SoftGuardClient  # noqa: E402
from app.services import auvo_service, rotas_service  # noqa: E402
from app.services.collector import credenciais_softguard  # noqa: E402

LIMITE_LISTA = 40


def _campos(registros, quantos=3):
    nomes = []
    for registro in registros[:quantos]:
        if isinstance(registro, dict):
            for chave in registro:
                if chave not in nomes:
                    nomes.append(chave)
    return nomes


def _amostra_endereco(registros, quantos=3):
    """O que o detector enxerga como endereço em cada registro — é a
    diferença entre "a API não manda" e "a API manda e eu não leio"."""
    linhas = []
    for registro in registros[:quantos]:
        lido = rotas_service._endereco_do_registro(registro)
        linhas.append(f"      {lido}")
    return linhas


def main() -> int:
    app = create_app()
    with app.app_context():
        print("== PowerCentral ==")
        client = SoftGuardClient(credenciais_softguard(app.config))
        contas = client.listar_todas_contas()
        print(f"{len(contas)} conta(s) no dealer")
        print("campos:", ", ".join(_campos(contas)))
        print("endereço lido das 3 primeiras:")
        for linha in _amostra_endereco(contas):
            print(linha)

        base = rotas_service._contas_base(contas)
        print(f"{len(base)} base (fora Villefort/Super Nosso/Apoio/interna)")

        print("\n== Auvo ==")
        auvo = auvo_service.criar_cliente(app.config)
        clientes = []
        if auvo is None:
            print("Auvo não configurada (sem chave/token em Configurações).")
        else:
            clientes = auvo.listar_clientes()
            print(f"{len(clientes)} cliente(s)")
            print("campos:", ", ".join(_campos(clientes)))
            print("endereço lido dos 3 primeiros:")
            for linha in _amostra_endereco(clientes):
                print(linha)
            com_bairro = sum(
                1
                for c in clientes
                if rotas_service._endereco_do_registro(c).bairro
            )
            print(f"{com_bairro} com bairro legível pela API")

        print("\n== Planilhas importadas ==")
        importacoes = rotas_service.resumo_importacoes()
        if not importacoes:
            print("nenhuma — o catálogo depende só do que as APIs derem.")
        for item in importacoes:
            print(
                f"  {item['fonte']}: {item['linhas']} linha(s), "
                f"{item['com_bairro']} com bairro, de {item['importado_em']:%d/%m/%Y %H:%M}"
            )

        print("\n== Catálogo ==")
        resultado = rotas_service.montar_catalogo(config=app.config)
        resumo = resultado["resumo"]
        print(
            f"base={resumo['base']}  com_bairro={resumo['com_bairro']}  "
            f"sem_bairro={resumo['sem_bairro']}  bairros={resumo['regioes']}"
        )
        print("origem do endereço:", resumo["fontes"])

        sem = [
            c
            for regiao in resultado["regioes"]
            if not regiao.tem_bairro
            for c in regiao.clientes
        ]
        if sem:
            print("\n-- sem bairro (fila do cadastro) --")
            for cliente in sem[:LIMITE_LISTA]:
                cidade = dom_end.titulo(cliente.cidade) or "sem nem a cidade"
                print(f"  {cliente.conta:>6}  {cliente.nome[:44]:<44} {cidade}")
            if len(sem) > LIMITE_LISTA:
                print(f"  ... e mais {len(sem) - LIMITE_LISTA}")

        print("\n== Conferência do recorte ==")
        from app.domain import disparos_geral as dom_disp

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
