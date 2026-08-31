import io

from app.extensions import db
from app.models.audit import AuditLog
from app.models.auvo import AuvoChamado, AuvoDepara
from app.services import auvo_service, settings_service


def _depara(conta="95", id_auvo=13804973, status="OK", nome="CLIENTE 95"):
    linha = AuvoDepara(conta_power=conta, nome_power=nome, id_auvo=id_auvo, status=status)
    db.session.add(linha)
    db.session.commit()
    return linha


class FakeAuvoClient:
    def __init__(self):
        self.payloads = []

    def criar_tarefa(self, payload):
        self.payloads.append(payload)
        return {"result": {"taskID": 777}}

    def listar_clientes(self):
        return [{"id": 555, "description": "CLIENTE NOVO LTDA"}]

    def listar_usuarios(self):
        return [{"userID": 238031, "name": "IGOR", "email": "igor@example.com"}]

    def listar_tipos_tarefa(self):
        return [{"id": 145696, "description": "ALARME"}]


# ---------- permissões ----------


def test_painel_requer_login(client):
    resposta = client.get("/chamados", follow_redirects=False)
    assert resposta.status_code == 302
    assert "/auth/login" in resposta.headers["Location"]


def test_operador_ve_painel_mas_nao_configuracao(operador_client):
    assert operador_client.get("/chamados").status_code == 200
    assert operador_client.get("/chamados/configuracao").status_code == 403
    assert operador_client.get("/chamados/depara").status_code == 403


def test_admin_ve_configuracao_e_depara(admin_client):
    assert admin_client.get("/chamados/configuracao").status_code == 200
    assert admin_client.get("/chamados/depara").status_code == 200


# ---------- painel ----------


def test_painel_mostra_historico_e_cards(app, admin_client):
    _depara()
    auvo_service.abrir_chamado(
        gatilho="sem_comunicacao",
        conta="95",
        nome="CLIENTE 95",
        contexto={"desde": "x", "sinal": "y"},
        config=app.config,
    )
    db.session.commit()

    resposta = admin_client.get("/chamados")
    assert resposta.status_code == 200
    assert b"simulada" in resposta.data
    assert "Simulação".encode() in resposta.data
    assert b"CLIENTE 95" in resposta.data


# ---------- configuração ----------


def test_admin_salva_configuracao(app, admin_client):
    resposta = admin_client.post(
        "/chamados/configuracao/salvar",
        data={
            "criador_id": "238031",
            "responsavel_id": "159336",
            "atribuir_responsavel": "y",
            "task_type": "145696",
            "task_type_sem_comunicacao": "145700",
            "priority": "3",
            "cooldown_horas": "24",
            "sem_comunicacao_horas_minimas": "4",
            "disparos_minimos_tarefa": "8",
            "disp_geral_minimos_tarefa": "40",
            "template_semcom_titulo": "Sem comunicacao - {conta}",
            "template_semcom_descricao": "Desde {desde}.",
            "template_disparos_titulo": "Disparos - {conta}",
            "template_disparos_descricao": "{qtd} disparos.",
        },
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    assert settings_service.get_auvo_criador_id() == 238031
    assert settings_service.get_auvo_task_type() == 145696
    assert settings_service.get_auvo_task_type_sem_comunicacao() == 145700
    assert settings_service.get_auvo_priority() == 3
    assert settings_service.get_auvo_cooldown_horas() == 24.0
    assert settings_service.get_auvo_disparos_minimos_tarefa() == 8
    assert settings_service.get_auvo_template("semcom", "titulo") == "Sem comunicacao - {conta}"
    assert AuditLog.query.filter_by(action="auvo_config_saved").count() == 1


def test_admin_salva_credenciais_cifradas(app, admin_client):
    resposta = admin_client.post(
        "/chamados/configuracao/credenciais",
        data={"api_key": "key-abc", "api_token": "token-xyz"},
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    assert settings_service.get_auvo_credentials(
        encryption_key=app.config["ENCRYPTION_KEY"]
    ) == ("key-abc", "token-xyz")
    assert "Configurado".encode() in resposta.data


def test_producao_exige_confirmacao_explicita(app, admin_client):
    resposta = admin_client.post(
        "/chamados/modo", data={"modo": "producao"}, follow_redirects=True
    )
    assert "preciso marcar a confirmação".encode() in resposta.data
    assert settings_service.auvo_simulacao() is True  # continua em simulação

    admin_client.post(
        "/chamados/modo", data={"modo": "producao", "confirmar": "sim"}, follow_redirects=True
    )
    assert settings_service.auvo_simulacao() is False
    evento = AuditLog.query.filter_by(action="auvo_mode_changed").one()
    assert evento.details["modo"] == "producao"

    admin_client.post("/chamados/modo", data={"modo": "simulacao"}, follow_redirects=True)
    assert settings_service.auvo_simulacao() is True


def test_testar_criacao_mostra_niveis_e_registra_historico(app, admin_client, monkeypatch):
    fake = FakeAuvoClient()
    monkeypatch.setattr(auvo_service, "criar_cliente", lambda config: fake)
    settings_service.set("auvo_criador_id", "238031")
    settings_service.set("auvo_task_type", "145696")
    settings_service.set("auvo_responsavel_id", "159336")
    db.session.commit()

    resposta = admin_client.post(
        "/chamados/testar", data={"customer_id": "13804973"}, follow_redirects=True
    )

    assert resposta.status_code == 200
    assert "mínimo (sem cliente)".encode() in resposta.data
    assert "com responsável".encode() in resposta.data
    assert b"777" in resposta.data
    assert len(fake.payloads) == 3  # três níveis executados
    assert AuvoChamado.query.filter_by(gatilho="teste", resultado="aberta").count() == 3


def test_auxiliares_listam_ids(app, admin_client, monkeypatch):
    monkeypatch.setattr(auvo_service, "criar_cliente", lambda config: FakeAuvoClient())

    resposta = admin_client.get("/chamados/auxiliares/usuarios")
    assert b"238031" in resposta.data
    assert b"IGOR" in resposta.data

    resposta = admin_client.get("/chamados/auxiliares/tipos")
    assert b"145696" in resposta.data

    assert admin_client.get("/chamados/auxiliares/naoexiste").status_code == 404


def test_auxiliares_sem_credenciais_avisa(admin_client):
    resposta = admin_client.get("/chamados/auxiliares/usuarios", follow_redirects=True)
    assert "Configure as credenciais".encode() in resposta.data


# ---------- de-para ----------


CSV = (
    "conta_power;nome_power;id_auvo;nome_auvo;score;status\n"
    "0095;CLINICA KENNEDY;13804973;CLINICA ESCOLA;1.00;OK\n"
    "66;JANGALITO;;;;REVISAR\n"
)


def test_importar_csv_pela_tela(app, admin_client):
    resposta = admin_client.post(
        "/chamados/depara/importar",
        data={"arquivo": (io.BytesIO(CSV.encode()), "depara.csv")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    assert "2 nova(s)".encode() in resposta.data
    assert AuvoDepara.query.count() == 2
    assert AuditLog.query.filter_by(action="auvo_depara_imported").count() == 1


def test_editar_vinculo_pela_tela(app, admin_client):
    linha = _depara(conta="66", id_auvo=None, status="REVISAR", nome="JANGALITO")

    resposta = admin_client.post(
        f"/chamados/depara/{linha.id}",
        data={"id_auvo": "999", "status": "OK"},
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    assert linha.id_auvo == 999
    assert linha.status == "OK"
    evento = AuditLog.query.filter_by(action="auvo_depara_edited").one()
    assert evento.details["para"]["id_auvo"] == 999


def test_filtro_do_depara(admin_client):
    _depara(conta="95", nome="CLINICA KENNEDY")
    _depara(conta="66", id_auvo=None, status="REVISAR", nome="JANGALITO")

    resposta = admin_client.get("/chamados/depara?q=KENNEDY")
    assert b"CLINICA KENNEDY" in resposta.data
    assert b"JANGALITO" not in resposta.data

    resposta = admin_client.get("/chamados/depara?status=REVISAR")
    assert b"JANGALITO" in resposta.data
    assert b"CLINICA KENNEDY" not in resposta.data


def test_regerar_pela_tela(app, admin_client, monkeypatch):
    monkeypatch.setattr(auvo_service, "criar_cliente", lambda config: FakeAuvoClient())
    _depara(conta="66", id_auvo=None, status="REVISAR", nome="CLIENTE NOVO")

    resposta = admin_client.post("/chamados/depara/regerar", follow_redirects=True)

    assert resposta.status_code == 200
    linha = AuvoDepara.query.filter_by(conta_power="66").one()
    assert linha.id_auvo == 555
    assert AuditLog.query.filter_by(action="auvo_depara_regenerated").count() == 1


def test_regerar_sem_credenciais_avisa(admin_client):
    resposta = admin_client.post("/chamados/depara/regerar", follow_redirects=True)
    assert "Configure as credenciais".encode() in resposta.data


# ---------- supressão (pausar / liberar) ----------


def test_pausar_conta_com_data_e_motivo(app, admin_client):
    from datetime import datetime, timezone

    linha = _depara(conta="95")

    resposta = admin_client.post(
        f"/chamados/depara/{linha.id}/suprimir",
        data={"suprimido_ate": "2026-08-01", "motivo": "aguardando cliente"},
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    assert linha.suprimido is True
    assert linha.suprimido_motivo == "aguardando cliente"
    assert linha.esta_suprimido(datetime(2026, 7, 30, tzinfo=timezone.utc)) is True
    assert linha.esta_suprimido(datetime(2026, 8, 5, tzinfo=timezone.utc)) is False
    from app.models.audit import AuditLog

    assert AuditLog.query.filter_by(action="auvo_depara_suprimida").count() == 1


def test_pausar_sem_data_fica_indefinida(app, admin_client):
    from datetime import datetime, timezone

    linha = _depara(conta="95")

    admin_client.post(
        f"/chamados/depara/{linha.id}/suprimir", data={}, follow_redirects=True
    )
    assert linha.suprimido is True
    assert linha.suprimido_ate is None
    # sem prazo: continua pausada em qualquer data futura
    assert linha.esta_suprimido(datetime(2027, 1, 1, tzinfo=timezone.utc)) is True


def test_liberar_conta(app, admin_client):
    from datetime import datetime, timezone

    linha = _depara(conta="95")
    linha.suprimido = True
    db.session.commit()

    admin_client.post(
        f"/chamados/depara/{linha.id}/liberar", data={}, follow_redirects=True
    )
    assert linha.suprimido is False
    assert linha.esta_suprimido(datetime.now(timezone.utc)) is False
    from app.models.audit import AuditLog

    assert AuditLog.query.filter_by(action="auvo_depara_liberada").count() == 1


def test_data_de_supressao_invalida_avisa(app, admin_client):
    linha = _depara(conta="95")

    resposta = admin_client.post(
        f"/chamados/depara/{linha.id}/suprimir",
        data={"suprimido_ate": "31/08/2026"},  # formato errado
        follow_redirects=True,
    )
    assert "inválida".encode() in resposta.data
    assert linha.suprimido is False  # não pausou


def test_operador_nao_pausa(operador_client, app):
    linha = _depara(conta="95")
    assert operador_client.post(f"/chamados/depara/{linha.id}/suprimir", data={}).status_code == 403


def test_filtro_so_pausadas(app, admin_client):
    ativa = _depara(conta="95", nome="ATIVA")
    pausada = _depara(conta="96", nome="PAUSADA")
    pausada.suprimido = True
    db.session.commit()

    resposta = admin_client.get("/chamados/depara?suprimidas=1")
    assert b"PAUSADA" in resposta.data
    assert b"ATIVA" not in resposta.data
