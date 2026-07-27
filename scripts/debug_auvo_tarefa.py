"""Diagnóstico: busca uma tarefa na Auvo e imprime o JSON cru, para
descobrirmos o campo de status (aberta/fechada/concluída). É temporário —
serve para construir a regra "só reabrir ordem se a anterior foi fechada".

Uso (no CMD, com o venv ativado, na pasta do projeto):
    python scripts\\debug_auvo_tarefa.py 77378377

Troque 77378377 por um ID de tarefa real que já foi aberto na Auvo.
Roda com o app, então pega as credenciais cifradas do banco (as mesmas
que a aba Chamados usa) — não precisa preencher nada.
"""

import json
import os
import sys

# o script fica em scripts/, mas o pacote "app" está na raiz do projeto —
# garante que a raiz esteja no path, rode de onde rodar
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.services import auvo_service


def _imprimir(client, path):
    print("=" * 70)
    print("GET", path)
    try:
        resp = client._request("GET", path, timeout=60)
    except Exception as exc:  # noqa: BLE001 - diagnóstico
        print("  erro na chamada:", exc)
        return
    print("  HTTP", resp.status_code)
    try:
        corpo = resp.json()
        print(json.dumps(corpo, ensure_ascii=False, indent=1)[:6000])
    except ValueError:
        print("  (resposta não-JSON):", resp.text[:1500])


def main():
    if len(sys.argv) < 2:
        print("Uso: python scripts\\debug_auvo_tarefa.py <ID_DA_TAREFA>")
        return
    task_id = sys.argv[1].strip()

    app = create_app()
    with app.app_context():
        client = auvo_service.criar_cliente(app.config)
        if client is None:
            print("Credenciais da Auvo não estão configuradas no site.")
            return
        # tenta os dois formatos de endpoint conhecidos da Auvo v2
        _imprimir(client, f"/tasks/{task_id}")
        _imprimir(client, f'/tasks/?paramFilter={{"taskID":{task_id}}}')


if __name__ == "__main__":
    main()
