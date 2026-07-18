from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models.watchdog import WatchdogState
from app.services import watchdog_service


class FakeTelegramClient:
    def __init__(self):
        self.mensagens: list[str] = []

    def enviar_mensagem(self, texto: str) -> list[str]:
        self.mensagens.append(texto)
        return ["fake-1"]


def test_sem_alerta_antes_do_primeiro_ciclo(app):
    telegram = FakeTelegramClient()

    resultado = watchdog_service.verificar(
        agora=datetime.now(timezone.utc), telegram_client=telegram
    )

    assert resultado is None
    assert telegram.mensagens == []


def test_sem_alerta_quando_dentro_do_limite(app):
    agora = datetime.now(timezone.utc)
    watchdog_service.registrar_ciclo_bem_sucedido(agora=agora - timedelta(minutes=5))
    db.session.commit()

    telegram = FakeTelegramClient()
    resultado = watchdog_service.verificar(agora=agora, limite_minutos=15, telegram_client=telegram)

    assert resultado is None
    assert telegram.mensagens == []


def test_alerta_dispara_uma_vez_quando_atraso_excede_limite(app):
    agora = datetime.now(timezone.utc)
    watchdog_service.registrar_ciclo_bem_sucedido(agora=agora - timedelta(minutes=20))
    db.session.commit()

    telegram = FakeTelegramClient()
    alerta = watchdog_service.verificar(agora=agora, limite_minutos=15, telegram_client=telegram)
    db.session.commit()

    assert alerta is not None
    assert alerta.message_type == "watchdog"
    assert alerta.cycle_id is None
    assert len(telegram.mensagens) == 1
    assert WatchdogState.query.first().alert_active is True

    # segunda verificação sem mudança de estado não deve reenviar
    alerta_repetido = watchdog_service.verificar(
        agora=agora, limite_minutos=15, telegram_client=telegram
    )
    assert alerta_repetido is None
    assert len(telegram.mensagens) == 1


def test_recuperacao_dispara_mensagem_quando_ciclo_volta(app):
    agora = datetime.now(timezone.utc)
    watchdog_service.registrar_ciclo_bem_sucedido(agora=agora - timedelta(minutes=20))
    db.session.commit()

    telegram = FakeTelegramClient()
    watchdog_service.verificar(agora=agora, limite_minutos=15, telegram_client=telegram)
    db.session.commit()

    watchdog_service.registrar_ciclo_bem_sucedido(agora=agora)
    db.session.commit()

    alerta = watchdog_service.verificar(agora=agora, limite_minutos=15, telegram_client=telegram)
    db.session.commit()

    assert alerta is not None
    assert alerta.message_type == "watchdog_recovery"
    assert len(telegram.mensagens) == 2
    assert WatchdogState.query.first().alert_active is False
