from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app.domain.dates import FUSO_HORARIO
from app.extensions import db
from app.integrations.telegram_client import TelegramClient
from app.models.cycle import AlertSent, CollectionCycle
from app.services import alerting, settings_service

logger = logging.getLogger("collector")


def talvez_enviar(
    *, agora: datetime, telegram_client: TelegramClient | None
) -> AlertSent | None:
    """Relatório periódico opcional no Telegram (independente de mudança de
    estado — complementa, não substitui, a regra 6.4). Só envia quando:
    a opção está ligada, já passou o intervalo configurado desde o último
    envio periódico, e existe ao menos um ciclo bem-sucedido para reportar.

    Pensado para ser chamado a cada minuto pelo scheduler — a checagem de
    intervalo aqui dentro faz mudanças de configuração valerem na hora,
    sem reagendamento de job."""
    if not settings_service.periodic_report_enabled():
        return None

    intervalo = timedelta(minutes=settings_service.get_periodic_report_interval_minutes())
    ultimo_envio = (
        AlertSent.query.filter_by(message_type="periodico")
        .order_by(AlertSent.sent_at.desc())
        .first()
    )
    if ultimo_envio is not None and agora - ultimo_envio.sent_at < intervalo:
        return None

    ultimo_ciclo = (
        CollectionCycle.query.filter_by(status="success")
        .order_by(CollectionCycle.finished_at.desc())
        .first()
    )
    if ultimo_ciclo is None:
        return None

    agora_local = agora.astimezone(FUSO_HORARIO)
    texto = (
        f"<b>Relatório periódico</b> — {agora_local.strftime('%d/%m/%Y %H:%M')}\n\n"
        + alerting.montar_relatorio_sem_comunicacao(
            ultimo_ciclo.accounts.all(), agora=agora_local
        )
    )

    alerta = alerting.registrar_e_enviar_alerta(
        telegram_client, cycle_id=ultimo_ciclo.id, tipo="periodico", texto=texto
    )
    # Mesmo relógio da checagem de intervalo acima — senão o carimbo
    # default (agora real) descasaria do "agora" recebido.
    alerta.sent_at = agora
    db.session.commit()
    logger.info("Relatório periódico enviado (ciclo %s).", ultimo_ciclo.id)
    return alerta
