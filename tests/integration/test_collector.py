from datetime import datetime, timezone

from app.integrations.softguard_client import SoftGuardError
from app.models.cycle import AlertSent, CollectionCycle, CycleAccount
from app.models.watchdog import WatchdogState
from app.services.collector import executar_ciclo


class FakeSoftGuardClient:
    def __init__(self, contas):
        self._contas = contas

    def buscar_contas_em_falha_tst(self, **kwargs):
        return self._contas


class ClienteSoftGuardQuebrado:
    def buscar_contas_em_falha_tst(self, **kwargs):
        raise SoftGuardError("portal fora do ar")


class FakeTelegramClient:
    def __init__(self):
        self.mensagens: list[str] = []

    def enviar_mensagem(self, texto: str) -> list[str]:
        self.mensagens.append(texto)
        return [f"fake-{len(self.mensagens)}"]


def _agora_formatada(delta_minutos: int = 0) -> str:
    from datetime import timedelta

    agora = datetime.now(timezone.utc) - timedelta(minutes=delta_minutos)
    return agora.strftime("%m/%d/%Y %I:%M:%S %p")


def _conta_sem_comunicacao(numero: str, evento_data: str) -> dict:
    return {
        "cue_ncuenta": numero,
        "cue_cnombre": f"Cliente {numero}",
        "sta_ncuentaenfallodetst": "1",
        "sta_tEnFalloDeTSTDesde": _agora_formatada(delta_minutos=6 * 60),
        "cue_cUltimaAlarmaRecibida": "PTB",
        "cue_dFechaUltimaAlarmaRecibida": evento_data,
    }


def _conta_comunicando(numero: str, evento_data: str) -> dict:
    return {
        "cue_ncuenta": numero,
        "cue_cnombre": f"Cliente {numero}",
        "sta_ncuentaenfallodetst": "1",
        "sta_tEnFalloDeTSTDesde": _agora_formatada(delta_minutos=6 * 60),
        "cue_cUltimaAlarmaRecibida": "TST",
        "cue_dFechaUltimaAlarmaRecibida": evento_data,
    }


def test_primeiro_ciclo_persiste_contas_e_envia_alerta_de_entrada(app):
    recente = _agora_formatada()
    telegram = FakeTelegramClient()

    cycle = executar_ciclo(
        config=app.config,
        softguard_client=FakeSoftGuardClient(
            [_conta_sem_comunicacao("1001", recente), _conta_comunicando("1002", recente)]
        ),
        telegram_client=telegram,
    )

    assert cycle.status == "success"
    assert cycle.total_em_falha_tst == 2
    assert cycle.total_sem_comunicacao == 1
    assert cycle.total_falso_positivo == 1
    assert CycleAccount.query.count() == 2

    alertas = AlertSent.query.all()
    assert len(alertas) == 1
    assert alertas[0].message_type == "entrada"
    assert alertas[0].accounts_added == ["1001"]
    assert len(telegram.mensagens) == 1

    # ciclo bem-sucedido também alimenta o watchdog (RF8)
    assert WatchdogState.query.first().last_successful_cycle_at is not None


def test_segundo_ciclo_sem_mudanca_nao_envia_alerta(app):
    recente = _agora_formatada()
    telegram = FakeTelegramClient()

    executar_ciclo(
        config=app.config,
        softguard_client=FakeSoftGuardClient([_conta_sem_comunicacao("1001", recente)]),
        telegram_client=telegram,
    )
    executar_ciclo(
        config=app.config,
        softguard_client=FakeSoftGuardClient([_conta_sem_comunicacao("1001", recente)]),
        telegram_client=telegram,
    )

    assert len(telegram.mensagens) == 1
    assert AlertSent.query.count() == 1
    assert CollectionCycle.query.count() == 2


def test_terceiro_ciclo_normaliza_e_envia_mensagem_de_normalizacao(app):
    recente = _agora_formatada()
    telegram = FakeTelegramClient()

    executar_ciclo(
        config=app.config,
        softguard_client=FakeSoftGuardClient([_conta_sem_comunicacao("1001", recente)]),
        telegram_client=telegram,
    )
    executar_ciclo(
        config=app.config,
        softguard_client=FakeSoftGuardClient([_conta_comunicando("1001", recente)]),
        telegram_client=telegram,
    )

    assert len(telegram.mensagens) == 2
    ultimo_alerta = AlertSent.query.order_by(AlertSent.id.desc()).first()
    assert ultimo_alerta.message_type == "normalizacao"


def test_ciclo_com_erro_do_portal_registra_status_error_e_nao_derruba(app):
    telegram = FakeTelegramClient()

    cycle = executar_ciclo(
        config=app.config,
        softguard_client=ClienteSoftGuardQuebrado(),
        telegram_client=telegram,
    )

    assert cycle.status == "error"
    assert "portal fora do ar" in cycle.error_message
    assert CycleAccount.query.count() == 0
    assert telegram.mensagens == []

    # o processo continua operável: um próximo ciclo bem-sucedido funciona normalmente
    recente = _agora_formatada()
    cycle2 = executar_ciclo(
        config=app.config,
        softguard_client=FakeSoftGuardClient([_conta_sem_comunicacao("1001", recente)]),
        telegram_client=telegram,
    )
    assert cycle2.status == "success"
