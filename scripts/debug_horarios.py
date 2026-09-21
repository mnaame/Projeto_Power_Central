"""Valida a Auditoria de Horários contra o portal real, ANTES de confiar nela.

O endpoint `/rest/search/Horario` com filtro `hor_iidcuenta` foi escrito a
partir do HAR, não de uma medição — e a regra do módulo depende inteiramente
dele: "nenhuma linha = conta sem horário". Se para conta sem horário o
portal devolvesse **erro** em vez de lista vazia, o módulo contaria tudo
como falha em vez de encontrar o que procura.

Este script confere isso numa amostra, antes de confiar na lista inteira.

Uso (PowerShell, na pasta do projeto — PARE o serviço antes, o portal
aceita uma sessão por usuário):

  Stop-Service PowerCentral
  .venv\\Scripts\\python.exe scripts\\debug_horarios.py
  Start-Service PowerCentral
"""

import os
import sys

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
        print(f"   {len(contas)} conta(s) — é esse o tamanho da varredura.")
        if not contas:
            print("   >>> Sem contas, não dá para seguir.")
            return
        print(f"   campos disponíveis: {', '.join(sorted(contas[0].keys()))}")

        print(f"\n2) HORÁRIOS — amostra de {AMOSTRA} conta(s)")
        print(f"   {'conta':>8}  {'linhas':>6}  resumo")
        campos_horario = set()
        sem = com = erros = 0
        for linha in contas[:AMOSTRA]:
            cue_iid = linha.get("cue_iid") or linha.get("Id")
            numero = str(linha.get("cue_ncuenta") or "").strip()
            if cue_iid is None:
                continue
            try:
                rows = client.listar_horarios(cue_iid)
            except Exception as exc:  # noqa: BLE001 — é isso que queremos ver
                erros += 1
                print(f"   {numero:>8}  {'ERRO':>6}  {type(exc).__name__}: {exc}")
                continue

            if rows:
                com += 1
                campos_horario.update(rows[0].keys())
            else:
                sem += 1
            print(
                f"   {numero:>8}  {len(rows):>6}  "
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
