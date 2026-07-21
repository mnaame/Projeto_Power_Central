from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.domain.classification import classificar_contas
from app.domain.dates import FUSO_HORARIO
from app.extensions import db
from app.integrations.softguard_client import SoftGuardClient, SoftGuardCredentials
from app.integrations.telegram_client import TelegramClient, TelegramCredentials
from app.models.cycle import CollectionCycle, CycleAccount
from app.services import alerting, settings_service, watchdog_service

logger = logging.getLogger("collector")


def credenciais_softguard(config) -> SoftGuardCredentials:
    return SoftGuardCredentials(
        host=config["SOFTGUARD_HOST"],
        port=config["SOFTGUARD_PORT"],
        client_id=config["SOFTGUARD_CLIENT_ID"],
        username=config["SOFTGUARD_USERNAME"],
        password=config["SOFTGUARD_PASSWORD"],
    )


def criar_cliente_telegram(config) -> TelegramClient | None:
    credenciais = settings_service.get_telegram_credentials(
        encryption_key=config["ENCRYPTION_KEY"]
    )
    if credenciais is None:
        return None
    token, chat_id = credenciais
    return TelegramClient(TelegramCredentials(bot_token=token, chat_id=chat_id))


def _ultimo_ciclo_bem_sucedido(*, excluindo_id: int | None) -> CollectionCycle | None:
    query = CollectionCycle.query.filter_by(status="success")
    if excluindo_id is not None:
        query = query.filter(CollectionCycle.id != excluindo_id)
    return query.order_by(CollectionCycle.finished_at.desc()).first()


def executar_ciclo(
    *,
    config,
    source: str = "scheduled",
    triggered_by_user_id: int | None = None,
    softguard_client: SoftGuardClient | None = None,
    telegram_client: TelegramClient | None = None,
) -> CollectionCycle:
    """Executa um ciclo completo do coletor (RF1): login -> consulta ->
    classificação -> persistência -> alertas -> watchdog.

    Nunca deixa uma falha do portal (ou qualquer outra exceção) propagar —
    vira um CollectionCycle com status=error, e o processo continua vivo
    (requisito de resiliência da seção 8)."""
    inicio = datetime.now(timezone.utc)
    cycle = CollectionCycle(
        started_at=inicio,
        status="running",
        source=source,
        triggered_by_user_id=triggered_by_user_id,
    )
    db.session.add(cycle)
    db.session.flush()

    try:
        client = softguard_client or SoftGuardClient(credenciais_softguard(config))
        contas_brutas = client.buscar_contas_em_falha_tst()

        agora_local = datetime.now(timezone.utc).astimezone(FUSO_HORARIO)
        contas_classificadas = classificar_contas(
            contas_brutas,
            agora=agora_local,
            janela_horas=settings_service.get_window_hours(),
            codigos_comprovadores=settings_service.get_confirming_codes(),
        )

        for conta in contas_classificadas:
            db.session.add(
                CycleAccount(
                    cycle_id=cycle.id,
                    account_number=conta.account_number,
                    account_name=conta.account_name,
                    tst_failure_since=conta.tst_failure_since,
                    last_event_code=conta.last_event_code,
                    last_event_at=conta.last_event_at,
                    classification=conta.classification,
                )
            )

        sem_comunicacao = [c for c in contas_classificadas if c.classification == "sem_comunicacao"]
        falso_positivo = [c for c in contas_classificadas if c.classification == "falso_positivo"]

        cycle.total_em_falha_tst = len(contas_classificadas)
        cycle.total_sem_comunicacao = len(sem_comunicacao)
        cycle.total_falso_positivo = len(falso_positivo)
        cycle.status = "success"
        cycle.finished_at = datetime.now(timezone.utc)

        anterior = _ultimo_ciclo_bem_sucedido(excluindo_id=cycle.id)
        anteriores_sem_comunicacao = (
            [a.account_number for a in anterior.accounts if a.classification == "sem_comunicacao"]
            if anterior is not None
            else []
        )

        cliente_telegram = (
            telegram_client if telegram_client is not None else criar_cliente_telegram(config)
        )
        alerting.processar_alertas(
            cycle=cycle,
            contas_atuais=contas_classificadas,
            contas_anteriores_sem_comunicacao=anteriores_sem_comunicacao,
            telegram_client=cliente_telegram,
            agora=agora_local,
        )

        watchdog_service.registrar_ciclo_bem_sucedido(agora=inicio)

    except Exception as exc:
        logger.exception("Ciclo do coletor (source=%s) falhou.", source)
        cycle.status = "error"
        cycle.error_message = str(exc)
        cycle.finished_at = datetime.now(timezone.utc)

    db.session.commit()
    return cycle
