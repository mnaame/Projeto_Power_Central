from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.domain.classification import SEM_COMUNICACAO, ContaClassificada


@dataclass(frozen=True)
class MudancaEstado:
    mudou: bool
    tipo: str | None  # "entrada" | "saida" | "normalizacao" | None
    contas_adicionadas: list[str]
    contas_removidas: list[str]


def contas_sem_comunicacao(contas: Iterable[ContaClassificada]) -> set[str]:
    return {c.account_number for c in contas if c.classification == SEM_COMUNICACAO}


def detectar_mudanca(anterior: Iterable[str], atual: Iterable[str]) -> MudancaEstado:
    """Compara o conjunto de contas sem comunicação do ciclo anterior com o
    atual (regra 6.4): alerta quando entra conta, sai conta, ou tudo
    normaliza (lista vazia após não vazia). Sem mudança = silêncio.
    """
    anterior_set = set(anterior)
    atual_set = set(atual)

    adicionadas = sorted(atual_set - anterior_set)
    removidas = sorted(anterior_set - atual_set)

    if not adicionadas and not removidas:
        return MudancaEstado(mudou=False, tipo=None, contas_adicionadas=[], contas_removidas=[])

    if not atual_set:
        tipo = "normalizacao"
    elif adicionadas:
        tipo = "entrada"
    else:
        tipo = "saida"

    return MudancaEstado(
        mudou=True, tipo=tipo, contas_adicionadas=adicionadas, contas_removidas=removidas
    )
