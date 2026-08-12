"""Minhas Tarefas — lógica pura de horizontes (dia/semana/fixa) e atraso.
Sem I/O; a leitura/escrita no banco fica em `services/tarefa_service.py`.
"""

from __future__ import annotations

from datetime import date, timedelta


def semana_corrente(referencia: date) -> tuple[date, date]:
    """Segunda a domingo da semana que contém `referencia`."""
    inicio = referencia - timedelta(days=referencia.weekday())
    return inicio, inicio + timedelta(days=6)


def esta_atrasada(data_tarefa: date | None, status: str, *, hoje: date) -> bool:
    """Atrasada = pendente com data no passado. Não muda nada sozinha — só
    marca pra exibição; quem decide o que fazer (concluir, remarcar ou
    puxar pro Dia) é o usuário."""
    return status == "pendente" and data_tarefa is not None and data_tarefa < hoje
