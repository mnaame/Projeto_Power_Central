from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.extensions import db
from app.models.audit import AuditLog
from app.models.auvo import AuvoChamado
from app.models.cycle import CollectionCycle
from app.models.report import ReportRun

logger = logging.getLogger("collector")


def limpar_dados_antigos(*, retention_days: int, agora: datetime | None = None) -> dict[str, int]:
    """Remove ciclos (com as contas e alertas associados, via cascade),
    eventos de auditoria, relatórios gerados (linha + arquivo .xlsx) e
    histórico de chamados Auvo mais antigos que `retention_days` (RF9).
    Pensado para rodar uma vez por dia, fora do horário de pico."""
    agora = agora or datetime.now(timezone.utc)
    limite = agora - timedelta(days=retention_days)

    ciclos_antigos = CollectionCycle.query.filter(CollectionCycle.started_at < limite).all()
    total_ciclos = len(ciclos_antigos)
    for cycle in ciclos_antigos:
        db.session.delete(cycle)

    total_auditoria = AuditLog.query.filter(AuditLog.timestamp < limite).delete(
        synchronize_session=False
    )

    relatorios_antigos = ReportRun.query.filter(ReportRun.generated_at < limite).all()
    total_relatorios = len(relatorios_antigos)
    for run in relatorios_antigos:
        if run.file_path:
            try:
                Path(run.file_path).unlink(missing_ok=True)
            except OSError:
                logger.warning("Retenção: não foi possível remover %s", run.file_path)
        db.session.delete(run)

    total_chamados = AuvoChamado.query.filter(AuvoChamado.criado_em < limite).delete(
        synchronize_session=False
    )

    db.session.commit()
    logger.info(
        "Retenção: removidos %s ciclos, %s eventos de auditoria, %s relatórios e "
        "%s chamados Auvo (limite=%s dias).",
        total_ciclos,
        total_auditoria,
        total_relatorios,
        total_chamados,
        retention_days,
    )
    return {
        "ciclos_removidos": total_ciclos,
        "auditoria_removida": total_auditoria,
        "relatorios_removidos": total_relatorios,
        "chamados_removidos": total_chamados,
    }
