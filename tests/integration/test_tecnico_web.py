from app.extensions import db
from app.models.auvo import AuvoDepara
from app.models.tecnico import TecnicoLote
from app.services import auvo_service, tecnico_service


class FakeAuvoClient:
    def __init__(self, tarefas=None):
        self.tarefas = tarefas or []

    def listar_tarefas(self, data_inicio, data_fim):
        return self.tarefas


class FakeSoftGuardClient:
    def __init__(self, contas=None, conteudo=b"<html><table><tr><td>Historico</td></tr></table></html>"):
        self.contas = contas or []
        self.conteudo = conteudo

    def listar_todas_contas(self, **kwargs):
        return self.contas

    def exportar_historico_html(self, **kwargs):
        return self.conteudo


def _depara(conta="95", id_auvo=13804973, status="OK", nome="CLINICA KENNEDY"):
    linha = AuvoDepara(conta_power=conta, nome_power=nome, id_auvo=id_auvo, status=status)
    db.session.add(linha)
    db.session.commit()
    return linha


def _tarefa(customer_id=13804973, tecnico="Alfredo Silva", nome="CLINICA KENNEDY"):
    return {
        "customerId": customer_id,
        "userToName": tecnico,
        "customerDescription": nome,
        "taskDate": "2026-07-31T08:00:00",
    }


# ---------- permissões ----------


def test_index_requer_login(client):
    resposta = client.get("/tecnico", follow_redirects=False)
    assert resposta.status_code == 302
    assert "/auth/login" in resposta.headers["Location"]


def test_operador_acessa_index(operador_client):
    assert operador_client.get("/tecnico").status_code == 200


# ---------- puxar agenda ----------


def test_puxar_agenda_sem_credenciais_mostra_aviso(operador_client):
    resposta = operador_client.post(
        "/tecnico/agenda",
        data={"data_agenda": "2026-07-31", "tecnico": "", "codigos": "CLO,OPN"},
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    assert "Credenciais da Auvo".encode() in resposta.data


def test_puxar_agenda_mostra_tabela_com_vinculo_e_sem_vinculo(app, operador_client, monkeypatch):
    _depara()
    fake_auvo = FakeAuvoClient(
        tarefas=[_tarefa(13804973), _tarefa(999999, nome="SEM VINCULO")]
    )
    monkeypatch.setattr(auvo_service, "criar_cliente", lambda config: fake_auvo)

    resposta = operador_client.post(
        "/tecnico/agenda",
        data={"data_agenda": "2026-07-31", "tecnico": "", "codigos": "CLO,OPN"},
    )
    assert resposta.status_code == 200
    assert b"CLINICA KENNEDY" in resposta.data
    assert b"SEM VINCULO" in resposta.data
    assert "sem vínculo".encode("utf-8") in resposta.data


# ---------- gerar lote ----------


def _form_geracao(**overrides):
    dados = {
        "data_agenda": "2026-07-31",
        "tecnico": "Alfredo",
        "dias_historico": "30",
        "periodo_inicio": "",
        "periodo_fim": "",
        "codigos": "CLO,OPN,BUR",
        "total_linhas": "1",
        "selecionar": "0",
        "conta_power_0": "95",
        "nome_loja_0": "CLINICA KENNEDY",
        "id_auvo_cliente_0": "13804973",
        "horario_0": "08:00",
        "codigos_0": "CLO,OPN,BUR",
    }
    dados.update(overrides)
    return dados


def test_gerar_lote_fluxo_completo_e_download(app, operador_client, monkeypatch):
    fake_softguard = FakeSoftGuardClient(
        contas=[{"cue_ncuenta": "0095", "cue_iid": "9385", "cue_cnombre": "CLINICA KENNEDY"}]
    )
    monkeypatch.setattr(tecnico_service, "_criar_cliente_softguard", lambda config: fake_softguard)

    resposta = operador_client.post("/tecnico/gerar", data=_form_geracao(), follow_redirects=True)
    assert resposta.status_code == 200
    assert b"gerado" in resposta.data

    lote = TecnicoLote.query.order_by(TecnicoLote.id.desc()).first()
    assert lote is not None
    assert lote.status == "success"
    assert lote.itens[0].conta_power == "95"
    assert lote.itens[0].status == "gerado"

    item = lote.itens[0]
    download = operador_client.get(f"/tecnico/lote/{lote.id}/item/{item.id}/download")
    assert download.status_code == 200
    assert b"Historico" in download.data

    zip_resposta = operador_client.get(f"/tecnico/lote/{lote.id}/zip")
    assert zip_resposta.status_code == 200
    assert zip_resposta.headers["Content-Type"] in ("application/zip", "application/x-zip-compressed")


def test_gerar_lote_sem_selecao_mostra_aviso(operador_client):
    dados = _form_geracao(selecionar="")
    del dados["selecionar"]
    resposta = operador_client.post("/tecnico/gerar", data=dados, follow_redirects=True)
    assert resposta.status_code == 200
    assert "Selecione ao menos uma loja".encode() in resposta.data


def test_gerar_lote_falha_isolada_aparece_no_detalhe(app, operador_client, monkeypatch):
    fake_softguard = FakeSoftGuardClient(contas=[])  # nenhuma conta -> item vira erro
    monkeypatch.setattr(tecnico_service, "_criar_cliente_softguard", lambda config: fake_softguard)

    resposta = operador_client.post("/tecnico/gerar", data=_form_geracao(), follow_redirects=True)
    assert resposta.status_code == 200
    assert "Conta não encontrada".encode("utf-8") in resposta.data

    lote = TecnicoLote.query.order_by(TecnicoLote.id.desc()).first()
    assert lote.status == "error"
    assert lote.itens[0].status == "erro"
