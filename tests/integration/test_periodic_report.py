from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models.cycle import AlertSent, CollectionCycle, CycleAccount
from app.services import periodic_report, settings_service

AGORA = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)


class FakeTelegramClient:
    def __init__(self):
        self.mensagens: list[str] = []

    def enviar_mensagem(self, texto: str) -> list[str]:
        self.mensagens.append(texto)
        return [f"fake-{len(self.mensagens)}"]


def _ciclo_com_conta():
    cycle = CollectionCycle(
        status="success", source="scheduled", started_at=AGORA, finished_at=AGORA
    )
    db.session.add(cycle)
    db.session.flush()
    db.session.add(
        CycleAccount(
            cycle_id=cycle.id,
            account_number="1001",
            account_name="Cliente Teste",
            classification="sem_comunicacao",
            last_event_code="PTB",
        )
    )
    db.session.commit()
    return cycle


def _ligar(intervalo="60"):
    settings_service.set("periodic_report_enabled", "true")
    settings_service.set("periodic_report_interval_minutes", intervalo)
    db.session.commit()


def test_desligado_por_padrao_nao_envia(app):
    _ciclo_com_conta()
    telegram = FakeTelegramClient()

    resultado = periodic_report.talvez_enviar(agora=AGORA, telegram_client=telegram)

    assert resultado is None
    assert telegram.mensagens == []


def test_ligado_sem_ciclo_nao_envia(app):
    _ligar()
    telegram = FakeTelegramClient()

    resultado = periodic_report.talvez_enviar(agora=AGORA, telegram_client=telegram)

    assert resultado is None


def test_ligado_envia_relatorio_com_contas(app):
    _ligar()
    _ciclo_com_conta()
    telegram = FakeTelegramClient()

    resultado = periodic_report.talvez_enviar(agora=AGORA, telegram_client=telegram)

    assert resultado is not None
    assert resultado.message_type == "periodico"
    assert resultado.success is True
    assert len(telegram.mensagens) == 1
    assert "Relatório periódico" in telegram.mensagens[0]
    assert "1001" in telegram.mensagens[0]


def test_respeita_intervalo_entre_envios(app):
    _ligar(intervalo="60")
    _ciclo_com_conta()
    telegram = FakeTelegramClient()

    periodic_report.talvez_enviar(agora=AGORA, telegram_client=telegram)
    resultado_cedo = periodic_report.talvez_enviar(
        agora=AGORA + timedelta(minutes=30), telegram_client=telegram
    )
    resultado_no_horario = periodic_report.talvez_enviar(
        agora=AGORA + timedelta(minutes=61), telegram_client=telegram
    )

    assert resultado_cedo is None
    assert resultado_no_horario is not None
    assert len(telegram.mensagens) == 2


def test_envia_mesmo_com_lista_vazia_como_heartbeat(app):
    _ligar()
    cycle = CollectionCycle(
        status="success", source="scheduled", started_at=AGORA, finished_at=AGORA
    )
    db.session.add(cycle)
    db.session.commit()
    telegram = FakeTelegramClient()

    resultado = periodic_report.talvez_enviar(agora=AGORA, telegram_client=telegram)

    assert resultado is not None
    assert "Nenhum cliente sem comunicação" in telegram.mensagens[0]


def test_alerta_periodico_gravado_em_alerts_sent(app):
    _ligar()
    _ciclo_com_conta()

    periodic_report.talvez_enviar(agora=AGORA, telegram_client=FakeTelegramClient())

    assert AlertSent.query.filter_by(message_type="periodico").count() == 1
