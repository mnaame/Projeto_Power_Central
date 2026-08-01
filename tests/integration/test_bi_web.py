from datetime import datetime, timedelta

from app.domain.dates import FUSO_HORARIO
from app.extensions import db
from app.models.auvo import AuvoDepara
from app.models.bi import BiRun
from app.services import auvo_service, bi_service, settings_service

AGORA = datetime.now(FUSO_HORARIO)
MARCO_FECHADO = AGORA - timedelta(days=20)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%m/%d/%Y %I:%M:%S %p")


class FakeAuvoClient:
    def __init__(self, tarefas=None):
        self.tarefas = tarefas or []

    def listar_tarefas(self, data_inicio, data_fim):
        return self.tarefas


class FakeSoftGuardClient:
    def __init__(self, eventos=None):
        self.eventos = eventos or []

    def buscar_historico(self, *, codigos_alarme, desde, hasta, **kwargs):
        return self.eventos


def _tarefa(customer_id, marco, tecnico="Alfredo Silva"):
    return {
        "customerId": customer_id,
        "finished": True,
        "taskStatus": 5,
        "userToName": tecnico,
        "taskType": 145696,
        "checkOutDatetime": marco.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _evento(conta, codigo, quando):
    return {
        "cue_ncuenta": conta,
        "cue_cnombre": f"CLIENTE {conta}",
        "rec_calarma": codigo,
        "rec_tfechahora": _fmt(quando),
        "rec_iidcuenta": "9385",
        "rec_iid": f"{conta}-{codigo}-{quando.timestamp()}",
    }


def _eventos_melhorou(conta="0095", marco=MARCO_FECHADO):
    return [_evento(conta, "BUR", marco - timedelta(days=d)) for d in (1, 2, 3, 4, 5)] + [
        _evento(conta, "BUR", marco + timedelta(days=1))
    ]


def _depara(conta="95", id_auvo=13804973, status="OK", nome="CLIENTE 95"):
    linha = AuvoDepara(conta_power=conta, nome_power=nome, id_auvo=id_auvo, status=status)
    db.session.add(linha)
    db.session.commit()
    return linha


# ---------- permissões ----------


def test_index_requer_login(client):
    resposta = client.get("/bi", follow_redirects=False)
    assert resposta.status_code == 302
    assert "/auth/login" in resposta.headers["Location"]


def test_operador_acessa_index(operador_client):
    assert operador_client.get("/bi").status_code == 200


def test_index_sem_run_mostra_estado_vazio(operador_client):
    resposta = operador_client.get("/bi")
    assert resposta.status_code == 200
    assert "Nenhum recálculo ainda".encode("utf-8") in resposta.data


# ---------- recalcular ----------


def test_recalcular_sem_credenciais_marca_erro_mas_nao_quebra(operador_client):
    resposta = operador_client.post(
        "/bi/recalcular", data={"periodo": "padrao", "tecnico": ""}, follow_redirects=True
    )
    assert resposta.status_code == 200
    assert "Recálculo terminou com erro".encode() in resposta.data
    assert BiRun.query.count() == 1
    assert BiRun.query.first().status == "error"


def test_recalcular_fluxo_completo_mostra_kpis_e_graficos(app, operador_client, monkeypatch):
    _depara(conta="95", id_auvo=13804973)
    fake_auvo = FakeAuvoClient(tarefas=[_tarefa(13804973, MARCO_FECHADO)])
    fake_softguard = FakeSoftGuardClient(eventos=_eventos_melhorou())
    monkeypatch.setattr(auvo_service, "criar_cliente", lambda config: fake_auvo)
    monkeypatch.setattr(bi_service, "_criar_cliente_softguard", lambda config: fake_softguard)

    resposta = operador_client.post(
        "/bi/recalcular", data={"periodo": "padrao", "tecnico": ""}, follow_redirects=True
    )
    assert resposta.status_code == 200
    assert b"BI recalculado" in resposta.data or "intervenção".encode("utf-8") in resposta.data
    assert b"CLIENTE 95" in resposta.data
    assert b"MELHOROU" in resposta.data

    run = BiRun.query.order_by(BiRun.id.desc()).first()
    assert run.status == "success"

    detalhe = operador_client.get(f"/bi/run/{run.id}")
    assert detalhe.status_code == 200
    assert b"CLIENTE 95" in detalhe.data


def test_recalcular_periodo_manual_invalido_mostra_aviso(operador_client):
    resposta = operador_client.post(
        "/bi/recalcular",
        data={"periodo": "manual", "inicio": "2026-08-10", "fim": "2026-08-01"},
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    assert "Período inválido".encode("utf-8") in resposta.data
    assert BiRun.query.count() == 0


def test_recalcular_bloqueia_execucao_concorrente(operador_client):
    assert bi_service._lock_recalculo.acquire(blocking=False) is True
    try:
        resposta = operador_client.post(
            "/bi/recalcular", data={"periodo": "padrao", "tecnico": ""}, follow_redirects=True
        )
        assert resposta.status_code == 200
        assert "em andamento".encode() in resposta.data
    finally:
        bi_service._lock_recalculo.release()


# ---------- exportação ----------


def test_exportar_intervencoes_e_cronicos(app, operador_client, monkeypatch):
    _depara(conta="95", id_auvo=13804973)
    marcos = [MARCO_FECHADO - timedelta(days=40), MARCO_FECHADO - timedelta(days=20), MARCO_FECHADO]
    tarefas = [_tarefa(13804973, marco) for marco in marcos]
    eventos = []
    for marco in marcos:
        eventos += _eventos_melhorou(conta="0095", marco=marco)

    fake_auvo = FakeAuvoClient(tarefas=tarefas)
    fake_softguard = FakeSoftGuardClient(eventos=eventos)
    monkeypatch.setattr(auvo_service, "criar_cliente", lambda config: fake_auvo)
    monkeypatch.setattr(bi_service, "_criar_cliente_softguard", lambda config: fake_softguard)

    operador_client.post("/bi/recalcular", data={"periodo": "padrao", "tecnico": ""})
    run = BiRun.query.order_by(BiRun.id.desc()).first()
    assert run.status == "success"

    resp_interv = operador_client.get(f"/bi/exportar/{run.id}/intervencoes")
    assert resp_interv.status_code == 200
    assert resp_interv.headers["Content-Type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    resp_cronicos = operador_client.get(f"/bi/exportar/{run.id}/cronicos")
    assert resp_cronicos.status_code == 200


def test_exportar_tabela_invalida_404(operador_client):
    assert operador_client.get("/bi/exportar/1/nao-existe").status_code == 404


def test_run_detalhe_inexistente_404(operador_client):
    assert operador_client.get("/bi/run/999999").status_code == 404


# ---------- configuração (admin) ----------


def test_operador_nao_acessa_configuracao(operador_client):
    assert operador_client.get("/bi/configuracao").status_code == 403


def test_admin_ve_e_salva_configuracao(app, admin_client):
    assert admin_client.get("/bi/configuracao").status_code == 200

    resposta = admin_client.post(
        "/bi/configuracao/salvar",
        data={
            "janela_dias": "10",
            "limiar_melhora": "15",
            "limiar_piora": "25",
            "tipos_intervencao": "145696,145697",
            "visitas_para_cronico": "4",
            "periodo_padrao_dias": "60",
            "amostra_minima_tecnico": "8",
        },
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    assert settings_service.get_bi_janela_dias() == 10
    assert settings_service.get_bi_limiar_melhora() == 15
    assert settings_service.get_bi_limiar_piora() == 25
    assert settings_service.get_bi_tipos_intervencao() == (145696, 145697)
    assert settings_service.get_bi_visitas_para_cronico() == 4
    assert settings_service.get_bi_periodo_padrao_dias() == 60
    assert settings_service.get_bi_amostra_minima_tecnico() == 8
