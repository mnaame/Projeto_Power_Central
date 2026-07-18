from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from app.domain.dates import FUSO_HORARIO
from app.extensions import db
from app.services import collector, collector_lock, settings_service, watchdog_service

logger = logging.getLogger("collector")

_scheduler: BackgroundScheduler | None = None


def _executar_ciclo_agendado(app) -> None:
    if not collector_lock.tentar_adquirir():
        logger.info("Ciclo agendado pulado: já há uma execução em andamento (manual).")
        return
    try:
        with app.app_context():
            collector.executar_ciclo(config=app.config, source="scheduled")
    finally:
        collector_lock.liberar()


def _executar_watchdog(app) -> None:
    with app.app_context():
        telegram_client = collector.criar_cliente_telegram(app.config)
        watchdog_service.verificar(
            agora=datetime.now(FUSO_HORARIO),
            limite_minutos=settings_service.get_watchdog_threshold_minutes(),
            telegram_client=telegram_client,
        )
        db.session.commit()


def iniciar(app) -> BackgroundScheduler:
    """Inicia o scheduler interno da aplicação (RF1): ciclo do coletor a
    cada N minutos (configurável) + verificação de watchdog a cada minuto —
    sem depender do Agendador de Tarefas do Windows. Ativado explicitamente
    via config START_SCHEDULER (ver .env.example), nunca automaticamente
    em comandos de CLI (migrations, seed-admin etc.)."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    with app.app_context():
        intervalo = settings_service.get_collector_interval_minutes()

    scheduler = BackgroundScheduler(timezone=FUSO_HORARIO)
    scheduler.add_job(
        _executar_ciclo_agendado,
        "interval",
        minutes=intervalo,
        args=[app],
        id="ciclo_coletor",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(FUSO_HORARIO),
    )
    scheduler.add_job(
        _executar_watchdog,
        "interval",
        minutes=1,
        args=[app],
        id="watchdog_check",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("Scheduler iniciado (ciclo do coletor a cada %s min).", intervalo)
    return scheduler


def parar() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def atualizar_intervalo_coletor(minutos: int) -> None:
    """Aplica um novo intervalo (RF7) ao job já em execução, sem precisar
    reiniciar o serviço. Não faz nada se o scheduler não estiver ativo
    (dev/testes/CLI) — a config já fica salva para a próxima subida."""
    if _scheduler is not None:
        _scheduler.reschedule_job("ciclo_coletor", trigger="interval", minutes=minutos)
