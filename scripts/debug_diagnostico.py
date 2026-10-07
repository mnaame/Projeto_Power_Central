"""Calibra o diagnóstico contra um export REAL de uma conta.

Duas coisas foram escritas sem ver um export de verdade, e as duas podem
estar erradas sem dar erro nenhum:

  1. **As colunas.** O diagnóstico lê data, evento e zona localizando as
     colunas pelo CABEÇALHO do export. Se o cabeçalho da zona não se
     chamar "Zona", o agrupamento por zona sai vazio — e um diagnóstico
     sem zona parece funcionar, só não diz onde está o problema.
  2. **Os códigos.** As listas de comunicação/bateria/AC/tamper vieram do
     catálogo genérico de painel de alarme. O código exato depende do
     MODELO do painel de cada cliente, então uma conta pode reportar
     falta de energia com um código que não está na lista.

Este script mostra o que o export traz de verdade: o cabeçalho, como cada
coluna foi mapeada, os códigos encontrados (com quantos de cada) e o
diagnóstico que sairia. Rode contra uma conta que você SABE que teve um
problema (ex.: queda de energia) e confira se ele aparece.

Uso (PowerShell, na pasta do projeto — PARE o serviço antes, o portal
aceita uma sessão por usuário):

  Stop-Service PowerCentral
  .venv\\Scripts\\python.exe scripts\\debug_diagnostico.py 95 [dias]
  Start-Service PowerCentral
"""

import os
import sys
from collections import Counter
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.domain import contas as dom_contas  # noqa: E402
from app.domain import diagnostico as dom_diag  # noqa: E402
from app.domain import tecnico as dom_tecnico  # noqa: E402
from app.domain.dates import FUSO_HORARIO  # noqa: E402
from app.integrations.softguard_client import (  # noqa: E402
    SoftGuardClient,
    SoftGuardError,
)
from app.services import collector, settings_service  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print("Falta a conta. Ex.: python scripts\\debug_diagnostico.py 95 15")
        return
    procurada = sys.argv[1].strip().lstrip("0")
    dias = int(sys.argv[2]) if len(sys.argv) > 2 else 15

    app = create_app()
    with app.app_context():
        client = SoftGuardClient(collector.credenciais_softguard(app.config))
        print("0) LOGIN...")
        try:
            client.login()
        except SoftGuardError as exc:
            print(f"   FALHOU: {exc}\n>>> O serviço PowerCentral está parado?")
            return
        print("   ok.\n")

        contas = dom_contas.contas_da_resposta(
            client.listar_todas_contas(incluir_particoes=True)
        )
        conta = next((c for c in contas if c.numero == procurada), None)
        if conta is None:
            print(f">>> Conta {procurada} não veio do portal. Veja scripts/debug_contas_faltando.py")
            return
        print(f"1) CONTA: {conta.rotulo} (cue_iid {conta.cue_iid}) — últimos {dias} dia(s)\n")

        hasta = datetime.now(FUSO_HORARIO)
        codigos = settings_service.get_diag_codigos_todos()
        print(f"2) PEDINDO O EXPORT com {len(codigos)} código(s): {','.join(codigos)}\n")
        conteudo = client.exportar_historico_html(
            cue_iid=conta.cue_iid,
            numero_conta=conta.numero,
            nome_cliente=conta.nome,
            desde=hasta - timedelta(days=dias),
            hasta=hasta,
            codigos_alarme=codigos,
        )

        linhas = dom_tecnico.linhas_do_export(conteudo)
        cabecalho = next((l for l in linhas if dom_tecnico.linha_e_cabecalho(l)), None)
        print(f"3) CABEÇALHO DO EXPORT ({len(linhas)} linha(s) no total)")
        if cabecalho is None:
            print("   >>> NÃO ACHEI o cabeçalho. O diagnóstico sai vazio assim.")
            print(f"   primeira linha crua: {[c.texto for c in linhas[0]] if linhas else '(nada)'}")
            return
        for indice, celula in enumerate(cabecalho):
            print(f"   [{indice}] {celula.texto!r}")

        col_data = dom_tecnico._indice_coluna(cabecalho, dom_tecnico._COLUNA_DATA)
        usados = [i for i in (col_data,) if i is not None]
        col_evento = dom_tecnico._indice_coluna(cabecalho, dom_tecnico._COLUNA_EVENTO, ignorar=usados)
        usados += [i for i in (col_evento,) if i is not None]
        col_zona = dom_tecnico._indice_coluna(cabecalho, dom_tecnico._COLUNA_ZONA, ignorar=usados)
        print("\n4) COLUNAS MAPEADAS")
        print(f"   data  -> {col_data}   evento -> {col_evento}   zona -> {col_zona}")
        if col_zona is None:
            print("   >>> SEM COLUNA DE ZONA: disparos e bypass não vão dizer a zona.")
            print("       Veja no cabeçalho acima como ela se chama e me avise.")

        eventos = dom_tecnico.eventos_do_export(conteudo)
        brutas = [l for l in linhas if not dom_tecnico.linha_e_cabecalho(l)]
        print(f"\n5) EVENTOS LIDOS: {len(eventos)} (de {len(brutas)} linha(s) de dados)")

        # As linhas CRUAS saem sempre, não só quando a leitura deu certo —
        # é exatamente quando ela falha que elas são necessárias, e a
        # primeira versão deste script só as imprimia em caso de sucesso.
        print("\n   PRIMEIRAS LINHAS CRUAS (célula por célula):")
        for linha in brutas[:3]:
            print("   ---")
            for indice, celula in enumerate(linha):
                print(f"     [{indice}] {celula.texto!r}")

        if eventos:
            print(f"\n   exemplo já convertido: {eventos[0]}")
        elif brutas:
            print(
                "\n   >>> O arquivo TEM linhas, mas nenhuma virou evento: o\n"
                "       código do evento não está onde eu procuro. Veja nas\n"
                "       linhas cruas acima em qual coluna ele aparece e me avise."
            )

        print("\n6) CÓDIGOS ENCONTRADOS (os que o diagnóstico NÃO conhece vão marcados)")
        conhecidos = set(codigos)
        for codigo, quantidade in Counter(
            str(e["rec_calarma"]) for e in eventos
        ).most_common():
            marca = "" if codigo in conhecidos else "   <- fora das listas"
            print(f"   {quantidade:>5}  {codigo}{marca}")

        print("\n7) ZONAS ENCONTRADAS")
        zonas = Counter(str(e["_zon_cdescripcion"] or "(vazio)") for e in eventos)
        for zona, quantidade in zonas.most_common(10):
            print(f"   {quantidade:>5}  {zona}")
        if list(zonas) == ["(vazio)"]:
            print("   >>> TODAS vazias — confira o mapeamento da coluna no passo 4.")

        print("\n8) DIAGNÓSTICO QUE SAIRIA NO TELEGRAM")
        achados = dom_diag.diagnosticar(
            eventos, cfg=settings_service.config_diagnostico(), dias=dias
        )
        print("   " + dom_diag.formatar_diagnostico(
            achados, numero_conta=conta.identificacao, nome_cliente=conta.nome, dias=dias
        ).replace("\n", "\n   "))

        print(
            "\n>>> Confira: o problema que você SABE que essa conta teve aparece\n"
            "    acima? Se não, olhe o passo 6 — se o código dele estiver\n"
            "    marcado como 'fora das listas', é só acrescentá-lo na\n"
            "    configuração correspondente (diag_codigos_*)."
        )


if __name__ == "__main__":
    main()
