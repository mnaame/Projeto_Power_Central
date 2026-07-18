from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class TZDateTime(TypeDecorator):
    """DateTime que sempre entra e sai timezone-aware em UTC.

    SQLite não tem tipo nativo com fuso — sem isso, um datetime aware vira
    naive ao ser recarregado do banco (a sessão expira os atributos após
    cada commit), e comparações passam a falhar com "can't subtract
    offset-naive and offset-aware datetimes"."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("TZDateTime requer um datetime timezone-aware.")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)
