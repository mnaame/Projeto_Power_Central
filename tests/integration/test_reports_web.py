from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models.audit import AuditLog
from app.models.report import ReportRun
from app.services import report_service, settings_service

FUSO = ZoneInfo("America/Sao_Paulo")


class FakeSoftGuardClient:
    def __init__(self, eventos=None, timelines=None):
        self.eventos = eventos or []
        self.timelines = timelines or {}

    def buscar_historico(self, **kwargs):
        return self.eventos

    def buscar_timeline(self, id_evento, **kwargs):
        return self.timelines.get(str(id_evento), [])


@pytest.fixture(autouse=True)
def _softguard_fake(monkeypatch):
    cliente = FakeSoftGuardClient(
        eventos=[
            {
                "rec_iid": "500",
                "rec_calarma": "NYE",
                "rec_tfechahora": "7/18/2026 9:30:00 PM",
                "cue_ncuenta": "0004",
                "cue_cnombre": "VILLEFORT TROPICAL",
                "rec_iidcuenta": "9385",
                "rec_ioperador": "7",
                "_zon_cdescripcion": "(28) IVP ENTRADA RM",
            }
        ],
        timelines={
            "500": [
                {
                    "etl_tFechaHora": "7/18/2026 9:30:00 PM",
                    "etl_cAccion": "Inicio",
                    "etl_cObservacion": "Evento recebido na Central",
                    "etl_iAccionCode": "",
                    "ope_cnombre": "",
                },
                {
                    "etl_tFechaHora": "7/18/2026 9:41:05 PM",
                    "etl_cAccion": "Procesar",
                    "etl_cObservacion": "Evento processado",
                    "etl_iAccionCode": "122",
                    "ope_cnombre": "MARIA",
                },
            ]
        },
    )
    monkeypatch.setattr(report_service, "_criar_cliente", lambda config: cliente)
    return cliente


def test_pagina_requer_login(client):
    resposta = client.get("/relatorios/atendimentos", follow_redirects=False)
    assert resposta.status_code == 302
    assert "/auth/login" in resposta.headers["Location"]


def test_modulo_desconhecido_da_404(operador_client):
    assert operador_client.get("/relatorios/naoexiste").status_code == 404


def test_pagina_vazia_antes_da_primeira_geracao(operador_client):
    resposta = operador_client.get("/relatorios/atendimentos")
    assert resposta.status_code == 200
    assert "Nenhum relatório gerado ainda".encode() in resposta.data


def test_operador_gera_atendimentos_e_ve_previa(app, operador_client, operador_user):
    resposta = operador_client.post(
        "/relatorios/atendimentos/gerar",
        data={"periodo": "ontem"},
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    assert "Relatório gerado com sucesso".encode() in resposta.data

    run = ReportRun.query.filter_by(module="atendimentos").one()
    assert run.status == "success"
    assert run.generated_by_user_id == operador_user.id

    # prévia lida do próprio xlsx — as colunas e a linha aparecem na tela
    assert b"DATA EVENTO" in resposta.data
    assert b"VILLEFORT TROPICAL" in resposta.data
    assert b"MARIA" in resposta.data

    evento = AuditLog.query.filter_by(action="report_generated").one()
    assert evento.result == "success"
    assert evento.details["module"] == "atendimentos"
    assert evento.details["row_count"] == 1


def test_download_do_arquivo_gerado(operador_client):
    operador_client.post(
        "/relatorios/atendimentos/gerar", data={"periodo": "ontem"}, follow_redirects=True
    )
    run = ReportRun.query.filter_by(module="atendimentos").one()

    resposta = operador_client.get(f"/relatorios/download/{run.id}")
    assert resposta.status_code == 200
    assert "attachment" in resposta.headers.get("Content-Disposition", "")
    assert resposta.data[:2] == b"PK"  # zip/xlsx


def test_download_inexistente_da_404(operador_client):
    assert operador_client.get("/relatorios/download/999").status_code == 404


def test_geracao_concorrente_bloqueada_com_feedback(app, operador_client):
    lock = report_service._locks["atendimentos"]
    assert lock.acquire(blocking=False)
    try:
        resposta = operador_client.post(
            "/relatorios/atendimentos/gerar", data={"periodo": "ontem"}, follow_redirects=True
        )
    finally:
        lock.release()

    assert "em andamento".encode() in resposta.data
    evento = AuditLog.query.filter_by(action="report_generated", result="failure").one()
    assert evento.details["motivo"] == "geracao_em_andamento"


def test_gerar_disparos_com_janela_automatica(app, operador_client):
    resposta = operador_client.post(
        "/relatorios/disparos/gerar", data={"periodo": "auto"}, follow_redirects=True
    )
    assert resposta.status_code == 200

    run = ReportRun.query.filter_by(module="disparos").one()
    assert run.status == "success"
    duracao = run.period_end - run.period_start
    assert abs(duracao - timedelta(hours=24)) < timedelta(minutes=1)


def test_gerar_com_periodo_manual(app, operador_client):
    resposta = operador_client.post(
        "/relatorios/atendimentos/gerar",
        data={"periodo": "manual", "inicio": "2026-07-01", "fim": "2026-07-02"},
        follow_redirects=True,
    )
    assert resposta.status_code == 200

    run = ReportRun.query.filter_by(module="atendimentos").one()
    assert run.period_start == datetime(2026, 7, 1, 0, 0, 0, tzinfo=FUSO)
    assert run.period_end == datetime(2026, 7, 2, 23, 59, 59, tzinfo=FUSO)


def test_periodo_manual_invalido_avisa_sem_gerar(operador_client):
    resposta = operador_client.post(
        "/relatorios/atendimentos/gerar",
        data={"periodo": "manual", "inicio": "2026-07-10", "fim": "2026-07-01"},
        follow_redirects=True,
    )
    assert "Período inválido".encode() in resposta.data
    assert ReportRun.query.count() == 0


def test_configuracoes_dos_relatorios_salvam(app, admin_client):
    from tests.integration.test_admin_settings import _dados_config

    admin_client.post(
        "/admin/configuracoes",
        data=_dados_config(
            atend_codigos_evento="nye, nyc, xyz",
            atend_incluir_abertos="y",
            disp_limite_recorrente="20",
            disp_ignorar_zonas="panico, teste",
        ),
        follow_redirects=True,
    )

    assert settings_service.get_atend_codigos_evento() == ("NYE", "NYC", "XYZ")
    assert settings_service.atend_incluir_abertos() is True
    assert settings_service.get_disp_limite_recorrente() == 20
    assert settings_service.get_disp_ignorar_zonas() == ("PANICO", "TESTE")
