"""Minhas Tarefas — lógica pura de horizontes (dia/semana/fixa) e atraso.
Sem I/O; a leitura/escrita no banco fica em `services/tarefa_service.py`.
"""

from __future__ import annotations

from datetime import date, timedelta


def semana_corrente(referencia: date) -> tuple[date, date]:
    """Segunda a domingo da semana que contém `referencia`."""
    inicio = referencia - timedelta(days=referencia.weekday())
    return inicio, inicio + timedelta(days=6)


def esta_atrasada(data_tarefa: date | None, status: str, *, horizonte: str, hoje: date) -> bool:
    """Atrasada = pendente com o período já encerrado. Pra Dia, o período
    é o próprio dia — atrasa assim que vira ontem. Pra Semana, o período é
    a semana inteira que contém `data` — não atrasa a cada dia que passa
    dentro da MESMA semana (bug real: tarefa criada na segunda não pode
    virar atrasada na terça), só quando a semana já acabou de verdade.
    Fixa não depende de `data` (nunca atrasa por aqui). Não muda nada
    sozinha — só marca pra exibição; quem decide o que fazer (concluir,
    remarcar ou puxar pro Dia) é o usuário."""
    if status != "pendente" or data_tarefa is None:
        return False
    if horizonte == "semana":
        inicio_semana_atual, _ = semana_corrente(hoje)
        return data_tarefa < inicio_semana_atual
    return data_tarefa < hoje
