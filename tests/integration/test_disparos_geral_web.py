from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.models.auvo import AuvoChamado, AuvoDepara
from app.models.report import ReportRun
from app.extensions import db
from app.services import report_service, settings_service

FUSO = ZoneInfo("America/Sao_Paulo")


class FakeSoftGuard:
    def __init__(self, eventos):
        self.eventos = eventos

    def buscar_historico(self, **kwargs):
        return self.eventos

    def buscar_timeline(self, id_evento, **kwargs):
        return []


def _fmt(dt):
    return dt.astimezone(FUSO).strftime("%m/%d/%Y %I:%M:%S %p")


def _bur(quando, *, conta, numero, nome, rec_iid):
    return {
        "rec_iid": rec_iid,
        "rec_iidcuenta": conta,
        "cue_ncuenta": numero,
        "cue_cnombre": nome,
        "rec_calarma": "BUR",
        "rec_tfechahora": _fmt(quando),
        "_zon_cdescripcion": "(28) IVP ENTRADA",
        "rec_ioperador": "0",
    }


@pytest.fixture(autouse=True)
def _fake_softguard(monkeypatch):
    base = datetime(2026, 7, 25, 22, 0, 0, tzinfo=FUSO)
    eventos = [
        _bur(base, conta="1", numero="10", nome="VILLEFORT HM", rec_iid="v1"),
        _bur(base, conta="2", numero="20", nome="SUPER NOSSO CASTELO", rec_iid="s1"),
        _bur(base, conta="3", numero="30", nome="ABC MERCADO", rec_iid="b1"),
    ]
    monkeypatch.setattr(report_service, "_criar_cliente", lambda config: FakeSoftGuard(eventos))


def test_pagina_disparos_geral_abre(operador_client):
    resposta = operador_client.get("/relatorios/disparos_geral")
    assert resposta.status_code == 200
    assert "Disparos Geral".encode() in resposta.data
    assert "Fim de semana atual".encode() in resposta.data  # preset no seletor


def test_gera_com_preset_fim_de_semana(app, operador_client):
    resposta = operador_client.post(
        "/relatorios/disparos_geral/gerar",
        data={"periodo": "fim_de_semana"},
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    run = ReportRun.query.filter_by(module="disparos_geral").one()
    assert run.status == "success"
    assert run.row_count == 3
    assert run.extra_counts["por_grupo"] == {"Villefort": 1, "Super Nosso": 1, "Base": 1}
    # sexta 18h -> segunda 08h (horário local)
    assert run.period_start.astimezone(FUSO).hour == 18
    assert run.period_end.astimezone(FUSO).hour == 8
    # prévia mostra os 3 grupos e os clientes
    assert b"VILLEFORT HM" in resposta.data
    assert b"SUPER NOSSO CASTELO" in resposta.data
    assert b"ABC MERCADO" in resposta.data


def test_gera_com_periodo_manual_hora(app, operador_client):
    resposta = operador_client.post(
        "/relatorios/disparos_geral/gerar",
        data={"periodo": "manual", "inicio": "2026-07-24T18:00", "fim": "2026-07-27T08:00"},
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    run = ReportRun.query.filter_by(module="disparos_geral").one()
    assert run.period_start == datetime(2026, 7, 24, 18, 0, tzinfo=FUSO)
    assert run.period_end == datetime(2026, 7, 27, 8, 0, tzinfo=FUSO)


def test_download_do_disparos_geral(operador_client):
    operador_client.post(
        "/relatorios/disparos_geral/gerar", data={"periodo": "fim_de_semana"}, follow_redirects=True
    )
    run = ReportRun.query.filter_by(module="disparos_geral").one()
    resposta = operador_client.get(f"/relatorios/download/{run.id}")
    assert resposta.status_code == 200
    assert resposta.data[:2] == b"PK"  # xlsx


def test_gatilho_auvo_abre_ordem_acima_do_limite(app, operador_client):
    # cliente com 1 disparo, limite Geral = 1 -> abre (em simulação)
    settings_service.set("auvo_disp_geral_minimos_tarefa", "1")
    db.session.add(
        AuvoDepara(conta_power="10", nome_power="VILLEFORT HM", id_auvo=13804850, status="OK")
    )
    db.session.commit()

    operador_client.post(
        "/relatorios/disparos_geral/gerar", data={"periodo": "fim_de_semana"}, follow_redirects=True
    )

    chamado = AuvoChamado.query.filter_by(conta_power="10").one()
    assert chamado.gatilho == "disparos"
    assert chamado.resultado == "simulada"  # simulação é o padrão


def test_gatilho_auvo_nao_abre_abaixo_do_limite(app, operador_client):
    settings_service.set("auvo_disp_geral_minimos_tarefa", "50")  # ninguém chega a 50
    db.session.add(
        AuvoDepara(conta_power="10", nome_power="VILLEFORT HM", id_auvo=13804850, status="OK")
    )
    db.session.commit()

    operador_client.post(
        "/relatorios/disparos_geral/gerar", data={"periodo": "fim_de_semana"}, follow_redirects=True
    )

    assert AuvoChamado.query.count() == 0
