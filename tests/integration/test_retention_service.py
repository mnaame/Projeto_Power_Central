from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models.audit import AuditLog
from app.models.cycle import AlertSent, CollectionCycle, CycleAccount
from app.services import retention_service

AGORA = datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)


def _cycle_em(quando):
    cycle = CollectionCycle(started_at=quando, finished_at=quando, status="success", source="scheduled")
    db.session.add(cycle)
    db.session.flush()
    db.session.add(
        CycleAccount(cycle_id=cycle.id, account_number="1001", classification="sem_comunicacao")
    )
    db.session.add(AlertSent(cycle_id=cycle.id, message_type="entrada", sent_at=quando))
    return cycle


def test_remove_ciclos_e_auditoria_mais_antigos_que_a_retencao(app):
    antigo = _cycle_em(AGORA - timedelta(days=100))
    recente = _cycle_em(AGORA - timedelta(days=10))
    db.session.add(AuditLog(action="login", result="success", timestamp=AGORA - timedelta(days=100)))
    db.session.add(AuditLog(action="login", result="success", timestamp=AGORA - timedelta(days=1)))
    db.session.commit()

    resultado = retention_service.limpar_dados_antigos(retention_days=90, agora=AGORA)

    assert resultado == {"ciclos_removidos": 1, "auditoria_removida": 1, "relatorios_removidos": 0}
    assert db.session.get(CollectionCycle, antigo.id) is None
    assert db.session.get(CollectionCycle, recente.id) is not None
    assert AuditLog.query.count() == 1


def test_cascade_remove_contas_e_alertas_do_ciclo_removido(app):
    antigo = _cycle_em(AGORA - timedelta(days=100))
    cycle_id = antigo.id
    db.session.commit()

    retention_service.limpar_dados_antigos(retention_days=90, agora=AGORA)

    assert CycleAccount.query.filter_by(cycle_id=cycle_id).count() == 0
    assert AlertSent.query.filter_by(cycle_id=cycle_id).count() == 0


def test_nao_remove_nada_quando_tudo_esta_dentro_da_retencao(app):
    _cycle_em(AGORA - timedelta(days=5))
    db.session.commit()

    resultado = retention_service.limpar_dados_antigos(retention_days=90, agora=AGORA)

    assert resultado == {"ciclos_removidos": 0, "auditoria_removida": 0, "relatorios_removidos": 0}
    assert CollectionCycle.query.count() == 1
