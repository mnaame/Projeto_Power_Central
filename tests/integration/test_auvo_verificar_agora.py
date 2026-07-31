import pytest

from app.extensions import db
from app.models.audit import AuditLog
from app.models.cycle import CollectionCycle
from app.models.report import ReportRun


class FakeSoftGuardClient:
    """Cobre os dois usos: coletor (sem comunicação) e report_service
    (disparos) — nenhuma conta em falha, nenhum evento, resposta rápida."""

    def __init__(self, *args, **kwargs):
        pass

    def buscar_contas_em_falha_tst(self, **kwargs):
        return []

    def buscar_historico(self, **kwargs):
        return []

    def buscar_timeline(self, id_evento, **kwargs):
        return []


@pytest.fixture(autouse=True)
def _softguard_rapido(monkeypatch):
    monkeypatch.setattr("app.services.collector.SoftGuardClient", FakeSoftGuardClient)
    monkeypatch.setattr("app.services.report_service.SoftGuardClient", FakeSoftGuardClient)


def test_verificar_agora_roda_os_dois_gatilhos(app, operador_client, operador_user):
    resposta = operador_client.post("/chamados/verificar-agora", follow_redirects=True)

    assert resposta.status_code == 200
    assert "Sem comunica".encode() in resposta.data
    assert "Disparos".encode() in resposta.data

    ciclo = CollectionCycle.query.order_by(CollectionCycle.id.desc()).first()
    assert ciclo is not None
    assert ciclo.source == "manual"
    assert ciclo.triggered_by_user_id == operador_user.id

    run = ReportRun.query.filter_by(module="disparos").order_by(ReportRun.id.desc()).first()
    assert run is not None
    assert run.status == "success"
    assert run.generated_by_user_id == operador_user.id

    eventos = {e.action for e in AuditLog.query.all()}
    assert "manual_update" in eventos
    assert "report_generated" in eventos


def test_operador_pode_clicar(operador_client):
    assert operador_client.post("/chamados/verificar-agora").status_code == 302


def test_requer_login(client):
    resposta = client.post("/chamados/verificar-agora", follow_redirects=False)
    assert resposta.status_code == 302
    assert "/auth/login" in resposta.headers["Location"]


def test_cooldown_da_sem_comunicacao_nao_impede_disparos(app, operador_client):
    # primeiro clique já gastou o cooldown do ciclo manual
    operador_client.post("/chamados/verificar-agora", follow_redirects=True)
    total_runs_disparos = ReportRun.query.filter_by(module="disparos").count()

    resposta = operador_client.post("/chamados/verificar-agora", follow_redirects=True)

    assert resposta.status_code == 200
    assert "aguarde".encode() in resposta.data  # sem comunicação bloqueada pelo cooldown
    # mas o relatório de disparos rodou de novo (lock independente)
    assert ReportRun.query.filter_by(module="disparos").count() == total_runs_disparos + 1
