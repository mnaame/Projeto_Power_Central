from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app.extensions import db
from app.integrations.telegram_client import TelegramClient
from app.models.cycle import AlertSent
from app.models.watchdog import WatchdogState
from app.services.alerting import registrar_e_enviar_alerta

logger = logging.getLogger("watchdog")

LIMITE_MINUTOS_PADRAO = 15.0


def obter_estado() -> WatchdogState:
    estado = WatchdogState.query.first()
    if estado is None:
        estado = WatchdogState(alert_active=False)
        db.session.add(estado)
        db.session.flush()
    return estado


def registrar_ciclo_bem_sucedido(*, agora: datetime) -> WatchdogState:
    """Chamado ao fim de todo ciclo bem-sucedido — atualiza o carimbo de
    última execução que `verificar` usa para detectar atraso (RF8)."""
    estado = obter_estado()
    estado.last_successful_cycle_at = agora
    return estado


def verificar(
    *,
    agora: datetime,
    limite_minutos: float = LIMITE_MINUTOS_PADRAO,
    telegram_client: TelegramClient | None,
) -> AlertSent | None:
    """Verifica se o coletor está atrasado (RF8): se ficar sem executar com
    sucesso por mais de `limite_minutos`, alerta uma única vez (não repete
    a cada verificação) e sinaliza `alert_active` para o painel; quando o
    coletor volta a rodar, envia a mensagem de recuperação. Deve ser
    chamado por um job próprio, independente do ciclo do coletor."""
    estado = obter_estado()

    if estado.last_successful_cycle_at is None:
        return None

    atraso = agora - estado.last_successful_cycle_at
    atrasado = atraso > timedelta(minutes=limite_minutos)

    if atrasado and not estado.alert_active:
        alerta = registrar_e_enviar_alerta(
            telegram_client,
            cycle_id=None,
            tipo="watchdog",
            texto=(
                "<b>Alerta de watchdog</b>\nO coletor não executa com sucesso há "
                f"{int(atraso.total_seconds() // 60)} minutos "
                f"(limite: {int(limite_minutos)} min)."
            ),
        )
        estado.alert_active = True
        estado.alert_sent_at = agora
        return alerta

    if not atrasado and estado.alert_active:
        alerta = registrar_e_enviar_alerta(
            telegram_client,
            cycle_id=None,
            tipo="watchdog_recovery",
            texto="<b>Watchdog recuperado</b>\nO coletor voltou a executar normalmente.",
        )
        estado.alert_active = False
        estado.alert_sent_at = agora
        return alerta

    return None
