"""Diagnóstico: valida o campo de DATA DE CONCLUSÃO usado pelo BI
Eficácia do Técnico (domain/bi.py) contra uma tarefa real da Auvo. O
critério de status (finished/taskStatus) já foi confirmado (tarefa
77330829); o campo de data ainda não — ver docs/BI_EFICACIA_TECNICO.md §6.

Uso (no CMD, com o venv ativado, na pasta do projeto):
    python scripts\\debug_bi_data_conclusao.py 77378377

Troque 77378377 por um ID de tarefa que você SABE que foi concluída e
sabe (ou pode conferir na Auvo) a data/hora real da conclusão. O script
mostra: se a tarefa é reconhecida como concluída, quais dos campos
candidatos existem no JSON, e a data que domain.bi.data_conclusao()
escolheria — compare com a data real da visita.

Se nenhum candidato bater, ou a data escolhida estiver clara e
consistentemente errada, ajuste `_CAMPOS_DATA_CONCLUSAO` em
`app/domain/bi.py` com o nome de campo certo (ele aparece no JSON
impresso abaixo) antes de confiar no ranking do BI para decisão.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.domain import bi as dom_bi
from app.services import auvo_service


def main():
    if len(sys.argv) < 2:
        print("Uso: python scripts\\debug_bi_data_conclusao.py <ID_DA_TAREFA>")
        return
    task_id = sys.argv[1].strip()

    app = create_app()
    with app.app_context():
        client = auvo_service.criar_cliente(app.config)
        if client is None:
            print("Credenciais da Auvo não estão configuradas no site.")
            return

        response = client._request("GET", f"/tasks/{task_id}", timeout=60)
        print("HTTP", response.status_code)
        try:
            corpo = response.json()
        except ValueError:
            print("resposta não-JSON:", response.text[:1500])
            return

        tarefa = corpo.get("result", corpo) if isinstance(corpo, dict) else corpo
        if not isinstance(tarefa, dict):
            print("Formato inesperado — JSON completo abaixo:")
            print(json.dumps(corpo, ensure_ascii=False, indent=1)[:6000])
            return

        print("=" * 70)
        print("JSON completo da tarefa:")
        print(json.dumps(tarefa, ensure_ascii=False, indent=1)[:6000])

        print("=" * 70)
        print("tarefa_concluida():", dom_bi.tarefa_concluida(tarefa))

        print("\nCandidatos de data de conclusão (nesta ordem de prioridade):")
        for campo in dom_bi._CAMPOS_DATA_CONCLUSAO:
            presente = campo in tarefa
            print(f"  {campo!r}: {'presente = ' + repr(tarefa[campo]) if presente else 'ausente'}")
        print(
            f"  {dom_bi._CAMPO_DATA_FALLBACK!r} (fallback, é a data AGENDADA, não a de conclusão): "
            f"{tarefa.get(dom_bi._CAMPO_DATA_FALLBACK)!r}"
        )

        marco = dom_bi.data_conclusao(tarefa)
        print(f"\ndata_conclusao() escolheria: {marco}")
        print("Confira essa data/hora contra a visita real antes de confiar no BI.")


if __name__ == "__main__":
    main()
