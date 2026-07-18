import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    AlertSent,
    AuditLog,
    CollectionCycle,
    CycleAccount,
    Setting,
    User,
    WatchdogState,
)
from app.security import hash_password, verify_password


def test_user_crud_and_password_hashing(app):
    user = User(
        username="admin", password_hash=hash_password("senha-forte-123"), role="admin"
    )
    db.session.add(user)
    db.session.commit()

    fetched = User.query.filter_by(username="admin").one()
    assert fetched.is_admin
    assert verify_password(fetched.password_hash, "senha-forte-123")
    assert not verify_password(fetched.password_hash, "senha-errada")


def test_user_role_constraint_rejects_invalid_role(app):
    db.session.add(User(username="x", password_hash="hash", role="superadmin"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_setting_roundtrip(app):
    db.session.add(Setting(key="window_hours", value="3"))
    db.session.commit()

    assert db.session.get(Setting, "window_hours").value == "3"


def test_collection_cycle_with_accounts_and_alert(app):
    cycle = CollectionCycle(
        status="success",
        source="scheduled",
        total_em_falha_tst=2,
        total_sem_comunicacao=1,
        total_falso_positivo=1,
    )
    db.session.add(cycle)
    db.session.flush()

    db.session.add_all(
        [
            CycleAccount(
                cycle_id=cycle.id, account_number="1001", classification="sem_comunicacao"
            ),
            CycleAccount(
                cycle_id=cycle.id, account_number="1002", classification="falso_positivo"
            ),
        ]
    )
    db.session.add(
        AlertSent(
            cycle_id=cycle.id,
            message_type="entrada",
            accounts_added=["1001"],
            accounts_removed=[],
            success=True,
        )
    )
    db.session.commit()

    assert cycle.accounts.count() == 2
    assert cycle.alerts.count() == 1


def test_cycle_account_classification_constraint(app):
    cycle = CollectionCycle(status="success", source="scheduled")
    db.session.add(cycle)
    db.session.flush()

    db.session.add(
        CycleAccount(cycle_id=cycle.id, account_number="1001", classification="invalida")
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_audit_log_and_watchdog_state(app):
    db.session.add(AuditLog(action="login", result="success", ip_address="10.0.0.5"))
    db.session.add(WatchdogState(alert_active=False))
    db.session.commit()

    assert AuditLog.query.count() == 1
    assert WatchdogState.query.count() == 1
