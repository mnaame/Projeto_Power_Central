"""Gatilhos Auvo ponta a ponta: o ciclo do coletor e a geração do
relatório de Disparos devem acionar a abertura de chamados (em simulação,
que é o padrão) sem que qualquer erro da Auvo derrube o fluxo original."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.extensions import db
from app.models.auvo import AuvoChamado, AuvoDepara
from app.services import report_service
from app.services.collector import executar_ciclo

FUSO = ZoneInfo("America/Sao_Paulo")


class FakeSoftGuardCollector:
    def __init__(self, contas):
        self._contas = contas

    def buscar_contas_em_falha_tst(self, **kwargs):
        return self._contas


class FakeSoftGuardReports:
    def __init__(self, eventos):
        self._eventos = eventos

    def buscar_historico(self, **kwargs):
        return self._eventos

    def buscar_timeline(self, id_evento, **kwargs):
        return []


def _fmt(dt):
    return dt.astimezone(FUSO).strftime("%m/%d/%Y %I:%M:%S %p")


def _depara(conta="95", id_auvo=13804973):
    db.session.add(
        AuvoDepara(conta_power=conta, nome_power="CLIENTE 95", id_auvo=id_auvo, status="OK")
    )
    db.session.flush()


def test_ciclo_do_coletor_abre_chamado_para_sem_comunicacao_antiga(app):
    _depara()
    agora = datetime.now(timezone.utc)
    conta = {
        "cue_ncuenta": "0095",
        "cue_cnombre": "CLIENTE 95",
        "sta_ncuentaenfallodetst": "1",
        "sta_tEnFalloDeTSTDesde": _fmt(agora - timedelta(hours=6)),
        "cue_cUltimaAlarmaRecibida": "PTB",  # não comprova comunicação
        "cue_dFechaUltimaAlarmaRecibida": _fmt(agora - timedelta(hours=6)),
    }

    ciclo = executar_ciclo(
        config=app.config,
        softguard_client=FakeSoftGuardCollector([conta]),
        telegram_client=None,
    )

    assert ciclo.status == "success"
    chamado = AuvoChamado.query.one()
    assert chamado.gatilho == "sem_comunicacao"
    assert chamado.conta_power == "95"
    assert chamado.resultado == "simulada"  # padrão: simulação ligada


def test_geracao_de_disparos_abre_chamado_a_partir_do_minimo(app):
    _depara()
    base = datetime(2026, 7, 18, 12, 0, 0, tzinfo=FUSO)
    eventos = [
        {
            "rec_iid": str(700 + i),
            "rec_iidcuenta": "9385",
            "cue_ncuenta": "0095",
            "cue_cnombre": "CLIENTE 95",
            "rec_calarma": "BUR",
            "rec_tfechahora": _fmt(base + timedelta(hours=i)),
            "_zon_cdescripcion": "(11) COFRE INTELIGENTE",
            "rec_ioperador": "0",
        }
        for i in range(5)  # exatamente o mínimo padrão
    ]

    run = report_service.gerar_disparos(
        config=app.config,
        user_id=None,
        desde=base - timedelta(hours=1),
        hasta=base + timedelta(hours=12),
        softguard_client=FakeSoftGuardReports(eventos),
    )

    assert run.status == "success"
    chamado = AuvoChamado.query.one()
    assert chamado.gatilho == "disparos"
    assert chamado.conta_power == "95"
    assert chamado.resultado == "simulada"
    assert "5 disparo(s)" in chamado.request_body["orientation"]


def test_erro_no_gatilho_auvo_nao_derruba_o_relatorio(app, monkeypatch):
    _depara()
    base = datetime(2026, 7, 18, 12, 0, 0, tzinfo=FUSO)
    eventos = [
        {
            "rec_iid": str(700 + i),
            "rec_iidcuenta": "9385",
            "cue_ncuenta": "0095",
            "cue_cnombre": "CLIENTE 95",
            "rec_calarma": "BUR",
            "rec_tfechahora": _fmt(base + timedelta(hours=i)),
            "_zon_cdescripcion": "(11) COFRE INTELIGENTE",
            "rec_ioperador": "0",
        }
        for i in range(5)
    ]

    from app.services import auvo_service

    def _explode(*args, **kwargs):
        raise RuntimeError("bug inesperado no gatilho")

    monkeypatch.setattr(auvo_service, "processar_disparos", _explode)

    run = report_service.gerar_disparos(
        config=app.config,
        user_id=None,
        desde=base - timedelta(hours=1),
        hasta=base + timedelta(hours=12),
        softguard_client=FakeSoftGuardReports(eventos),
    )

    assert run.status == "success"  # relatório intacto
    assert AuvoChamado.query.count() == 0
