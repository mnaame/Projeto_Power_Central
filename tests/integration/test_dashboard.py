from datetime import datetime, timezone

from app.extensions import db
from app.models.cycle import CollectionCycle, CycleAccount


def test_dashboard_mostra_estado_vazio_quando_nao_ha_ciclos(operador_client):
    resposta = operador_client.get("/")
    assert resposta.status_code == 200
    assert "Nenhum cliente sem comunicação".encode() in resposta.data


def test_dashboard_mostra_contas_sem_comunicacao(app, operador_client):
    cycle = CollectionCycle(
        status="success", source="scheduled", finished_at=datetime.now(timezone.utc)
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

    resposta = operador_client.get("/")
    assert resposta.status_code == 200
    assert b"1001" in resposta.data
    assert "Cliente Teste".encode() in resposta.data
    assert b"PTB" in resposta.data


def test_dashboard_esconde_falsos_positivos_dos_criticos(app, operador_client):
    cycle = CollectionCycle(
        status="success", source="scheduled", finished_at=datetime.now(timezone.utc)
    )
    db.session.add(cycle)
    db.session.flush()
    db.session.add(
        CycleAccount(
            cycle_id=cycle.id,
            account_number="2002",
            account_name="Cliente Comunicando",
            classification="falso_positivo",
            last_event_code="TST",
        )
    )
    db.session.commit()

    resposta = operador_client.get("/")
    assert resposta.status_code == 200
    assert "Nenhum cliente sem comunicação".encode() in resposta.data
    assert b"2002" in resposta.data  # aparece na secao de falsos positivos


def test_dashboard_partial_endpoint_retorna_fragmento(operador_client):
    resposta = operador_client.get("/dashboard/painel")
    assert resposta.status_code == 200
    assert b"<html" not in resposta.data.lower()
    assert b"<!doctype" not in resposta.data.lower()
