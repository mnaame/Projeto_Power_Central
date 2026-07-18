from __future__ import annotations

from datetime import datetime, timezone

from app.models.cycle import CollectionCycle
from app.services import collector, collector_lock, settings_service


class CicloEmAndamentoError(Exception):
    """Já existe um ciclo em execução (agendado ou manual) — o botão fica
    bloqueado até liberar (critério de aceite: segundo clique bloqueado)."""


class CooldownAtivoError(Exception):
    def __init__(self, segundos_restantes: float):
        self.segundos_restantes = max(int(segundos_restantes), 0)
        super().__init__(f"Aguarde {self.segundos_restantes}s antes de atualizar de novo.")


def disparar_manual(
    *,
    config,
    user_id: int | None,
    softguard_client=None,
    telegram_client=None,
) -> CollectionCycle:
    """Dispara um ciclo manual (RF4): cooldown desde o último ciclo
    concluído, e exclusão mútua com qualquer outro ciclo em andamento via
    lock compartilhado com o scheduler (app/services/collector_lock.py).

    `softguard_client`/`telegram_client` só existem para injeção em
    testes — em produção o coletor monta os dois a partir da config."""
    ultimo_concluido = (
        CollectionCycle.query.filter(CollectionCycle.finished_at.isnot(None))
        .order_by(CollectionCycle.finished_at.desc())
        .first()
    )
    if ultimo_concluido is not None:
        cooldown = settings_service.get_manual_cooldown_seconds()
        decorrido = (datetime.now(timezone.utc) - ultimo_concluido.finished_at).total_seconds()
        if decorrido < cooldown:
            raise CooldownAtivoError(cooldown - decorrido)

    if not collector_lock.tentar_adquirir():
        raise CicloEmAndamentoError()

    try:
        return collector.executar_ciclo(
            config=config,
            source="manual",
            triggered_by_user_id=user_id,
            softguard_client=softguard_client,
            telegram_client=telegram_client,
        )
    finally:
        collector_lock.liberar()
