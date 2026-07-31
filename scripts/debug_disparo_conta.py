"""Diagnóstico: mostra como cada disparo (BUR) de uma conta foi classificado
no relatório de Disparos Aleatórios, e quais arme/desarme o sistema viu
(inclusive ROP/RCL remotos). Serve para entender por que um cliente entrou
como "aleatório".

Uso (CMD, venv ativado, na pasta do projeto):
  python scripts\\debug_disparo_conta.py "<busca>" <inicio> <fim>

  <busca>  = parte do nome do cliente OU número da conta (entre aspas se tiver espaço)
  <inicio> / <fim> = 2026-07-30T18:00  (data e hora, com o T no meio)

Ex.:
  python scripts\\debug_disparo_conta.py "SUPER NOSSO CAICARA" 2026-07-30T18:00 2026-07-31T08:00
"""

import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.domain import disparos as dom  # noqa: E402
from app.services import report_service, settings_service  # noqa: E402

FUSO = ZoneInfo("America/Sao_Paulo")


def _parse(texto: str) -> datetime:
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, fmt).replace(tzinfo=FUSO)
        except ValueError:
            continue
    raise SystemExit(f"Data inválida: {texto!r} — use o formato 2026-07-30T18:00")


def _hora(quando) -> str:
    return quando.astimezone(FUSO).strftime("%d/%m %H:%M:%S") if quando else "??/?? ??:??:??"


def main():
    if len(sys.argv) < 4:
        print('Uso: python scripts\\debug_disparo_conta.py "<busca>" <inicio> <fim>')
        print('Ex.:  python scripts\\debug_disparo_conta.py "SUPER NOSSO CAICARA" '
              '2026-07-30T18:00 2026-07-31T08:00')
        return

    busca = sys.argv[1].strip().upper()
    inicio, fim = _parse(sys.argv[2]), _parse(sys.argv[3])
    print(f"Período: {_hora(inicio)} -> {_hora(fim)}  |  buscando por: {busca!r}")

    app = create_app()
    with app.app_context():
        client = report_service._criar_cliente(app.config)
        folga = timedelta(minutes=6)
        codigos = (dom.CODIGO_DISPARO,) + dom.CODIGOS_ARME + dom.CODIGOS_DESARME
        print(f"Códigos consultados: {', '.join(codigos)}")
        eventos = client.buscar_historico(
            codigos_alarme=codigos,
            desde=(inicio - folga).astimezone(FUSO),
            hasta=(fim + folga).astimezone(FUSO),
        )
        na_janela = dom.filtrar_para_janela(eventos, desde=inicio, hasta=fim)
        grupos = dom.agrupar_por_conta(na_janela)
        zonas_ignoradas = settings_service.get_disp_ignorar_zonas()

        achou = False
        for _conta_id, rows in grupos.items():
            nome = numero = ""
            for evento in rows:
                nome = nome or dom._texto(evento.get("cue_cnombre"))
                numero = numero or dom._texto(evento.get("cue_ncuenta"))
            if busca not in f"{numero} {nome}".upper():
                continue
            achou = True

            print("=" * 72)
            print(f"CONTA {numero} - {nome}")
            print("   --- arme / desarme vistos pelo sistema ---")
            def _chave(evento):
                q = dom._quando(evento)
                return q or datetime.max.replace(tzinfo=FUSO)
            achou_arme_desarme = False
            for evento in sorted(rows, key=_chave):
                cod = dom._codigo_evento(evento)
                if cod in dom.CODIGOS_ARME:
                    achou_arme_desarme = True
                    print(f"   {_hora(dom._quando(evento))}  {cod:4s} [ARME]")
                elif cod in dom.CODIGOS_DESARME:
                    achou_arme_desarme = True
                    print(f"   {_hora(dom._quando(evento))}  {cod:4s} [DESARME]")
            if not achou_arme_desarme:
                print("   (nenhum arme/desarme no período — todo BUR fica 'aleatório')")

            print("   --- disparos (BUR) e classificação ---")
            avaliados = dom.avaliar_disparos_da_conta(rows, zonas_ignoradas=zonas_ignoradas)
            if not avaliados:
                print("   (nenhum BUR no período)")
            for d in avaliados:
                if d.valido:
                    verdict = "VÁLIDO  -> entra como ALEATÓRIO"
                else:
                    verdict = f"EXCLUÍDO -> {d.motivo_exclusao}"
                print(f"   {_hora(d.quando)}  BUR  {(d.zona or '')[:28]:28s} {verdict}")

        if not achou:
            print(f"Nenhuma conta encontrada com {busca!r} no período.")


if __name__ == "__main__":
    main()
