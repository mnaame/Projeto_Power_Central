from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models.audit import AuditLog
from app.models.cycle import CollectionCycle

logger = logging.getLogger("collector")


def limpar_dados_antigos(*, retention_days: int, agora: datetime | None = None) -> dict[str, int]:
    """Remove ciclos (com as contas e alertas associados, via cascade) e
    eventos de auditoria mais antigos que `retention_days` (RF9). Pensado
    para rodar uma vez por dia, fora do horário de pico."""
    agora = agora or datetime.now(timezone.utc)
    limite = agora - timedelta(days=retention_days)

    ciclos_antigos = CollectionCycle.query.filter(CollectionCycle.started_at < limite).all()
    total_ciclos = len(ciclos_antigos)
    for cycle in ciclos_antigos:
        db.session.delete(cycle)

    total_auditoria = AuditLog.query.filter(AuditLog.timestamp < limite).delete(
        synchronize_session=False
    )

    db.session.commit()
    logger.info(
        "Retenção: removidos %s ciclos e %s eventos de auditoria (limite=%s dias).",
        total_ciclos,
        total_auditoria,
        retention_days,
    )
    return {"ciclos_removidos": total_ciclos, "auditoria_removida": total_auditoria}
