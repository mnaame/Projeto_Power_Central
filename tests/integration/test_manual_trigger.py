import pytest

from app.extensions import db
from app.models.audit import AuditLog
from app.models.cycle import CollectionCycle


class FakeSoftGuardClient:
    def __init__(self, *args, **kwargs):
        pass

    def buscar_contas_em_falha_tst(self, **kwargs):
        return []


@pytest.fixture(autouse=True)
def _softguard_rapido(monkeypatch):
    # sem isso, o botão tentaria acessar https://None:None de verdade e
    # gastaria segundos em retry/backoff antes de falhar
    monkeypatch.setattr("app.services.collector.SoftGuardClient", FakeSoftGuardClient)


def test_operador_dispara_atualizacao_manual(app, operador_client, operador_user):
    resposta = operador_client.post("/dashboard/atualizar", follow_redirects=True)
    assert resposta.status_code == 200
    assert "Atualiza".encode() in resposta.data

    cycle = CollectionCycle.query.order_by(CollectionCycle.id.desc()).first()
    assert cycle.source == "manual"
    assert cycle.triggered_by_user_id == operador_user.id
    assert cycle.status == "success"

    evento = AuditLog.query.filter_by(action="manual_update").first()
    assert evento is not None
    assert evento.result == "success"
    assert evento.user_id == operador_user.id


def test_segundo_clique_seguido_e_bloqueado_por_cooldown(operador_client):
    operador_client.post("/dashboard/atualizar", follow_redirects=True)
    resposta = operador_client.post("/dashboard/atualizar", follow_redirects=True)

    assert resposta.status_code == 200
    assert "Aguarde".encode() in resposta.data

    bloqueados = AuditLog.query.filter_by(action="manual_update", result="failure").count()
    assert bloqueados == 1


def test_atualizacao_manual_requer_login(client):
    resposta = client.post("/dashboard/atualizar", follow_redirects=False)
    assert resposta.status_code == 302
    assert "/auth/login" in resposta.headers["Location"]
