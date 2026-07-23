from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.domain.classification import ContaClassificada
from app.domain.disparos import ClienteComDisparos
from app.extensions import db
from app.integrations.auvo_client import AuvoError
from app.models.audit import AuditLog
from app.models.auvo import AuvoChamado, AuvoDepara
from app.services import auvo_service, settings_service

FUSO = ZoneInfo("America/Sao_Paulo")


class FakeAuvoClient:
    def __init__(self, resposta=None, erro: AuvoError | None = None, clientes=None):
        self.resposta = resposta if resposta is not None else {"result": {"taskID": 4242}}
        self.erro = erro
        self.clientes = clientes or []
        self.payloads: list[dict] = []

    def criar_tarefa(self, payload):
        self.payloads.append(payload)
        if self.erro is not None:
            raise self.erro
        return self.resposta

    def listar_clientes(self):
        return self.clientes


def _depara(conta="95", id_auvo=13804973, status="OK", nome_power="CLIENTE 95"):
    linha = AuvoDepara(
        conta_power=conta, nome_power=nome_power, id_auvo=id_auvo, status=status
    )
    db.session.add(linha)
    db.session.flush()
    return linha


def _producao(criador="238031", task_type="145696", responsavel="", atribuir="false"):
    settings_service.set("auvo_simulacao", "false")
    settings_service.set("auvo_criador_id", criador)
    settings_service.set("auvo_task_type", task_type)
    settings_service.set("auvo_responsavel_id", responsavel)
    settings_service.set("auvo_atribuir_responsavel", atribuir)


def _abrir(app, client=None, conta="0095", nome="CLIENTE 95", gatilho="sem_comunicacao"):
    return auvo_service.abrir_chamado(
        gatilho=gatilho,
        conta=conta,
        nome=nome,
        contexto={"desde": "22/07/2026 03:00", "sinal": "TST em 22/07/2026 00:01"},
        config=app.config,
        client=client,
    )


# ---------- de-para ----------


def test_conta_fora_do_depara_vira_sem_depara_uma_unica_vez(app):
    chamado = _abrir(app)
    assert chamado.resultado == "sem_depara"

    # anti-ruído: repetir dentro da janela não cria outra linha
    assert _abrir(app) is None
    assert AuvoChamado.query.count() == 1


def test_depara_nao_ou_sem_id_nao_abre(app):
    _depara(conta="95", status="NAO")
    _depara(conta="96", id_auvo=None, status="OK")

    assert _abrir(app, conta="95").resultado == "sem_depara"
    assert _abrir(app, conta="0096").resultado == "sem_depara"


def test_conta_com_zeros_a_esquerda_encontra_depara(app):
    _depara(conta="95")
    chamado = _abrir(app, conta="0095")  # PowerCentral usa zeros à esquerda
    assert chamado.resultado == "simulada"


# ---------- simulação ----------


def test_simulacao_registra_payload_sem_chamar_api(app):
    _depara()
    fake = FakeAuvoClient()

    chamado = _abrir(app, client=fake)

    assert chamado.resultado == "simulada"
    assert fake.payloads == []  # nada foi enviado
    assert chamado.request_body["customerId"] == 13804973
    # título do template na 1ª linha da orientation (§2 regra 6)
    assert chamado.request_body["orientation"].startswith("Cliente sem comunicacao - 95")
    evento = AuditLog.query.filter_by(action="auvo_chamado").one()
    assert evento.details["resultado"] == "simulada"


def test_simulada_nao_bloqueia_execucao_real_depois(app):
    _depara()
    _abrir(app)  # simulada
    _producao()

    chamado = _abrir(app, client=FakeAuvoClient())

    assert chamado.resultado == "aberta"  # simulação não gravou dedup


# ---------- produção ----------


def test_aberta_monta_payload_validado(app):
    _depara()
    _producao(responsavel="159336", atribuir="true")
    fake = FakeAuvoClient()

    chamado = _abrir(app, client=fake)

    assert chamado.resultado == "aberta"
    assert chamado.id_tarefa_auvo == "4242"
    payload = fake.payloads[0]
    assert payload["customerId"] == 13804973
    assert payload["taskType"] == 145696
    assert payload["priority"] == 2
    assert payload["idUserFrom"] == 238031
    assert payload["idUserTo"] == 159336
    assert "keyWords" not in payload  # §2 regra 6
    titulo, descricao = payload["orientation"].split("\n", 1)
    assert titulo == "Cliente sem comunicacao - 95 CLIENTE 95"
    assert "22/07/2026 03:00" in descricao


def test_atribuir_desligado_omite_iduserto(app):
    _depara()
    _producao(responsavel="159336", atribuir="false")
    fake = FakeAuvoClient()

    _abrir(app, client=fake)

    assert "idUserTo" not in fake.payloads[0]  # §2 regra 5


def test_cooldown_bloqueia_reabertura(app):
    _depara()
    _producao()
    fake = FakeAuvoClient()

    assert _abrir(app, client=fake).resultado == "aberta"
    segundo = _abrir(app, client=fake)

    assert segundo.resultado == "repetida"
    assert len(fake.payloads) == 1  # não chamou a API de novo
    assert _abrir(app, client=fake) is None  # anti-ruído da 'repetida'


def test_falha_guarda_corpo_e_resposta(app):
    _depara()
    _producao()
    erro = AuvoError(
        "Auvo recusou a criação da tarefa (HTTP 400).",
        status=400,
        corpo_enviado={"customerId": 13804973},
        resposta={"errorCode": 124},
    )

    chamado = _abrir(app, client=FakeAuvoClient(erro=erro))

    assert chamado.resultado == "falha"
    assert chamado.request_body == {"customerId": 13804973}
    assert chamado.response_body == {"errorCode": 124}
    assert "400" in chamado.erro
    evento = AuditLog.query.filter_by(action="auvo_chamado").one()
    assert evento.result == "failure"


def test_criador_ausente_em_producao_vira_falha_clara(app):
    _depara()
    _producao(criador="")

    chamado = _abrir(app, client=FakeAuvoClient())

    assert chamado.resultado == "falha"
    assert "idUserFrom" in chamado.erro


def test_credenciais_ausentes_em_producao_vira_falha(app):
    _depara()
    _producao()

    chamado = _abrir(app, client=None)  # sem client injetado e sem credenciais

    assert chamado.resultado == "falha"
    assert "Credenciais" in chamado.erro


# ---------- réguas dos gatilhos ----------


def _conta_classificada(horas_em_falha: float, numero="0095") -> ContaClassificada:
    agora = datetime.now(FUSO)
    return ContaClassificada(
        account_number=numero,
        account_name="CLIENTE 95",
        tst_failure_since=agora - timedelta(hours=horas_em_falha),
        last_event_code="PTB",
        last_event_at=agora - timedelta(hours=horas_em_falha),
        classification="sem_comunicacao",
    )


def test_sem_comunicacao_so_abre_apos_horas_minimas(app):
    _depara()
    agora = datetime.now(FUSO)

    abertos = auvo_service.processar_sem_comunicacao(
        [_conta_classificada(2.0)], config=app.config, agora=agora
    )
    assert abertos == []  # 2h < mínimo de 3h

    abertos = auvo_service.processar_sem_comunicacao(
        [_conta_classificada(4.0)], config=app.config, agora=agora
    )
    assert len(abertos) == 1
    assert abertos[0].resultado == "simulada"
    assert abertos[0].gatilho == "sem_comunicacao"


def _cliente_disparos(quantidade: int) -> ClienteComDisparos:
    return ClienteComDisparos(
        conta_id="9385",
        conta_numero="0095",
        cliente="CLIENTE 95",
        quantidade=quantidade,
        ocorrencia="ALEATORIO",
        zonas=("(11) COFRE INTELIGENTE",),
        ids_eventos_atendidos=(),
    )


def test_disparos_so_abre_a_partir_do_minimo(app):
    _depara()

    assert (
        auvo_service.processar_disparos([_cliente_disparos(4)], config=app.config) == []
    )

    abertos = auvo_service.processar_disparos([_cliente_disparos(5)], config=app.config)
    assert len(abertos) == 1
    chamado = abertos[0]
    assert chamado.gatilho == "disparos"
    assert chamado.conta_power == "95"  # veio de cue_ncuenta normalizado
    assert "5 disparo(s)" in chamado.request_body["orientation"]
    assert "(11) COFRE INTELIGENTE" in chamado.request_body["orientation"]


# ---------- de-para: importação e regeração ----------


CSV_EXEMPLO = """conta_power;nome_power;id_auvo;nome_auvo;score;status
0095;CLINICA KENNEDY;13804973;CLÍNICA ESCOLA VETERINÁRIA KENNEDY LTDA;1.00;OK
1;NOVO MILLENIUM;13804702;O NOVO MILLENIUM;0.90;Não
66;JANGALITO;;;;REVISAR
"""


def test_importar_depara_csv_normaliza_conta_e_status(app):
    resultado = auvo_service.importar_depara_csv(CSV_EXEMPLO)

    assert resultado == {"criadas": 3, "atualizadas": 0, "ignoradas": 0}
    kennedy = AuvoDepara.query.filter_by(conta_power="95").one()  # "0095" normalizada
    assert kennedy.id_auvo == 13804973
    assert kennedy.status == "OK"
    assert AuvoDepara.query.filter_by(conta_power="1").one().status == "NAO"  # "Não"
    jangalito = AuvoDepara.query.filter_by(conta_power="66").one()
    assert jangalito.id_auvo is None
    assert jangalito.status == "REVISAR"

    # reimportar faz upsert, não duplica
    resultado = auvo_service.importar_depara_csv(CSV_EXEMPLO)
    assert resultado["atualizadas"] == 3
    assert AuvoDepara.query.count() == 3


def test_regerar_depara_preserva_linhas_revisadas(app):
    revisada = _depara(conta="95", id_auvo=111, status="OK", nome_power="CLIENTE 95")
    _depara(conta="66", id_auvo=None, status="REVISAR", nome_power="JANGALITO")
    fake = FakeAuvoClient(
        clientes=[
            {"id": 999, "description": "JANGALITO COMERCIO LTDA"},
            {"id": 888, "description": "OUTRA EMPRESA QUALQUER"},
        ]
    )

    resultado = auvo_service.regerar_depara(client=fake)

    assert resultado == {"recasadas": 1, "preservadas": 1}
    assert revisada.id_auvo == 111  # revisão humana intacta
    jangalito = AuvoDepara.query.filter_by(conta_power="66").one()
    assert jangalito.id_auvo == 999
    assert jangalito.nome_auvo == "JANGALITO COMERCIO LTDA"
    assert jangalito.status in ("OK", "REVISAR")
    assert jangalito.score > 0.5
