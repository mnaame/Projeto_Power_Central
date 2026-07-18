from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol, TypeVar

_SEM_DATA = datetime(9999, 1, 1, tzinfo=timezone.utc)


class _ComFalhaDesde(Protocol):
    tst_failure_since: datetime | None


T = TypeVar("T", bound=_ComFalhaDesde)


def ordenar_por_falha_mais_antiga(contas: list[T]) -> list[T]:
    """Mais antigo em falha primeiro (regra 5). Contas sem data de falha
    conhecida vão para o final. Funciona tanto com ContaClassificada
    (domínio) quanto com CycleAccount (modelo) — qualquer objeto com
    `tst_failure_since`."""

    def chave(conta: _ComFalhaDesde) -> tuple[bool, datetime]:
        data = conta.tst_failure_since
        return (data is None, data or _SEM_DATA)

    return sorted(contas, key=chave)
