import pytest

from app.extensions import db
from app.services import collector_lock, settings_service, trigger_service


class FakeSoftGuardClient:
    def buscar_contas_em_falha_tst(self, **kwargs):
        return []


class FakeTelegramClient:
    def enviar_mensagem(self, texto):
        return ["fake-1"]


def _disparar(app, user_id=None):
    return trigger_service.disparar_manual(
        config=app.config,
        user_id=user_id,
        softguard_client=FakeSoftGuardClient(),
        telegram_client=FakeTelegramClient(),
    )


def test_disparar_manual_cria_ciclo(app):
    cycle = _disparar(app)
    assert cycle.status == "success"
    assert cycle.source == "manual"


def test_disparar_manual_bloqueia_por_cooldown(app):
    _disparar(app)

    with pytest.raises(trigger_service.CooldownAtivoError) as exc_info:
        _disparar(app)
    assert exc_info.value.segundos_restantes > 0


def test_disparar_manual_permite_de_novo_apos_cooldown_zero(app):
    settings_service.set("manual_cooldown_seconds", "0")
    db.session.commit()

    _disparar(app)
    cycle2 = _disparar(app)
    assert cycle2.source == "manual"


def test_disparar_manual_bloqueado_quando_lock_ocupado(app):
    assert collector_lock.tentar_adquirir() is True
    try:
        with pytest.raises(trigger_service.CicloEmAndamentoError):
            _disparar(app)
    finally:
        collector_lock.liberar()


def test_disparar_manual_libera_lock_apos_execucao(app):
    _disparar(app)
    assert collector_lock.em_execucao() is False
