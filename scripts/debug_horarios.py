"""Valida a Auditoria de Horários contra o portal real, ANTES de confiar nela.

Duas coisas foram escritas a partir do HAR e da leitura do código, não de
uma medição — e este script existe para fechar essa lacuna:

  1. **`/rest/search/Horario` com filtro `hor_iidcuenta`.** A regra do
     módulo é "nenhuma linha = conta sem horário". Se o endpoint devolvesse
     erro (em vez de lista vazia) para conta sem horário, o módulo contaria
     tudo como erro em vez de encontrar o que procura.
  2. **De onde vem o tipo da conta.** O `CuentaByDealer` identifica o tipo
     por número (o mesmo `_tip_nTipo` do filtro da tela "Falha TST") e a
     descrição sai do catálogo `t_CuentasTipoServicio`. Os nomes exatos dos
     campos variam de tela para tela no portal, então o código procura por
     uma lista de candidatos — aqui a gente vê quais existem de verdade.

Se o tipo não aparecer, o módulo continua funcionando: a coluna vira "—" e
essas contas NUNCA são escondidas pelo filtro (melhor auditar a mais do que
deixar passar batido). Mas aí o filtro "Comercial" perde a serventia, e é
melhor saber disso agora.

Uso (PowerShell, na pasta do projeto — PARE o serviço antes, o portal
aceita uma sessão por usuário):

  Stop-Service PowerCentral
  .venv\\Scripts\\python.exe scripts\\debug_horarios.py
  Start-Service PowerCentral
"""

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.domain import horarios as dom_horarios  # noqa: E402
from app.integrations.softguard_client import (  # noqa: E402
    SoftGuardClient,
    SoftGuardError,
)
from app.services import collector  # noqa: E402

# Quantas contas sondar de verdade. A varredura completa é o produto; aqui
# só queremos confirmar o formato sem castigar o portal.
AMOSTRA = 12


def main() -> None:
    app = create_app()
    with app.app_context():
        client = SoftGuardClient(collector.credenciais_softguard(app.config))

        print("0) LOGIN...")
        try:
            client.login()
        except SoftGuardError as exc:
            print(
                f"   FALHOU: {exc}\n\n"
                ">>> 'Invalid Token' aqui costuma ser disputa de sessão:\n"
                "    confira se o serviço PowerCentral está parado e se o\n"
                "    portal não está aberto no navegador com o mesmo usuário."
            )
            return
        print("   ok.\n")

        print("1) CONTAS (CuentaByDealer)")
        contas = client.listar_todas_contas()
        print(f"   {len(contas)} conta(s).")
        if not contas:
            print("   >>> Sem contas, não dá para seguir.")
            return

        chaves = sorted(contas[0].keys())
        print(f"   campos disponíveis: {', '.join(chaves)}\n")

        achados_texto = [c for c in dom_horarios.CAMPOS_TIPO_TEXTO
                         if c in {k.lower() for k in chaves}]
        achados_numero = [c for c in dom_horarios.CAMPOS_TIPO_NUMERO
                          if c in {k.lower() for k in chaves}]
        print(f"   campo de tipo TEXTO encontrado:  {achados_texto or 'NENHUM'}")
        print(f"   campo de tipo NÚMERO encontrado: {achados_numero or 'NENHUM'}")

        print("\n2) CATÁLOGO DE TIPOS (t_CuentasTipoServicio)")
        try:
            linhas_catalogo = client.listar_tipos_servico()
            print(f"   {len(linhas_catalogo)} linha(s).")
            if linhas_catalogo:
                print(f"   campos: {', '.join(sorted(linhas_catalogo[0].keys()))}")
            catalogo = dom_horarios.catalogo_de_tipos(linhas_catalogo)
            print(f"   traduzido: {catalogo or 'VAZIO — os nomes dos campos não bateram'}")
        except SoftGuardError as exc:
            catalogo = {}
            print(f"   FALHOU: {exc}")
            print("   >>> Sem catálogo o tipo fica '—'. O módulo funciona,")
            print("       mas o filtro por tipo perde a serventia.")

        print("\n3) TIPO RESOLVIDO POR CONTA (como o módulo vai ver)")
        tipos = Counter(dom_horarios.tipo_da_conta(linha, catalogo) for linha in contas)
        for tipo, quantidade in tipos.most_common():
            print(f"   {quantidade:>4}  {tipo}")
        if list(tipos) == [dom_horarios.TIPO_DESCONHECIDO]:
            print(
                "\n   >>> TODAS desconhecidas. O filtro por tipo não vai\n"
                "       recortar nada (e, por segurança, não esconde\n"
                "       ninguém). Use o filtro por nome na tela."
            )

        print(f"\n4) HORÁRIOS — amostra de {AMOSTRA} conta(s)")
        print(f"   {'conta':>8}  {'linhas':>6}  {'tipo':<14}  resumo")
        campos_horario = set()
        sem = com = erros = 0
        for linha in contas[:AMOSTRA]:
            cue_iid = linha.get("cue_iid") or linha.get("Id")
            numero = str(linha.get("cue_ncuenta") or "").strip()
            tipo = dom_horarios.tipo_da_conta(linha, catalogo)
            if cue_iid is None:
                continue
            try:
                rows = client.listar_horarios(cue_iid)
            except Exception as exc:  # noqa: BLE001 — é isso que queremos ver
                erros += 1
                print(f"   {numero:>8}  {'ERRO':>6}  {tipo:<14}  {type(exc).__name__}: {exc}")
                continue

            if rows:
                com += 1
                campos_horario.update(rows[0].keys())
            else:
                sem += 1
            print(
                f"   {numero:>8}  {len(rows):>6}  {tipo:<14}  "
                f"{dom_horarios.resumo_horario(rows) or '(sem horário)'}"
            )

        print(f"\n   com horário: {com} | sem horário: {sem} | erro: {erros}")
        if campos_horario:
            print(f"   campos de uma linha de horário: {', '.join(sorted(campos_horario))}")

        if erros and not (com or sem):
            print(
                "\n>>> TODAS deram erro. Ou o endpoint /rest/search/Horario está\n"
                "    diferente do que o HAR mostrou, ou o usuário de integração\n"
                "    não tem permissão nele. Me mande esta saída."
            )
        elif sem and not com:
            print(
                "\n>>> Nenhuma conta da amostra tem horário. Pode ser verdade,\n"
                "    mas confira UMA conta que você SABE que tem horário\n"
                "    cadastrado antes de confiar na lista inteira."
            )
        else:
            print("\n>>> Formato confirmado: lista vazia = conta sem horário.")


if __name__ == "__main__":
    main()
