from datetime import datetime
from zoneinfo import ZoneInfo

from app.domain.classification import ContaClassificada
from app.extensions import db
from app.models.cycle import AlertSent, CollectionCycle
from app.services import alerting

FUSO = ZoneInfo("America/Sao_Paulo")
AGORA = datetime(2026, 7, 18, 12, 0, 0, tzinfo=FUSO)


class FakeTelegramClient:
    def __init__(self):
        self.mensagens: list[str] = []

    def enviar_mensagem(self, texto: str) -> list[str]:
        self.mensagens.append(texto)
        return [f"fake-{len(self.mensagens)}"]


def _conta(numero, classification, falha_desde=None, evento_codigo=None, evento_data=None, nome=None):
    return ContaClassificada(
        account_number=numero,
        account_name=nome if nome is not None else f"Cliente {numero}",
        tst_failure_since=falha_desde,
        last_event_code=evento_codigo,
        last_event_at=evento_data,
        classification=classification,
    )


def test_relatorio_ordena_do_mais_antigo_para_o_mais_recente():
    contas = [
        _conta("1002", "sem_comunicacao", falha_desde=datetime(2026, 7, 17, 10, 0, tzinfo=FUSO)),
        _conta("1001", "sem_comunicacao", falha_desde=datetime(2026, 7, 16, 8, 0, tzinfo=FUSO)),
    ]
    texto = alerting.montar_relatorio_sem_comunicacao(contas, agora=AGORA)
    assert texto.index("1001") < texto.index("1002")


def test_relatorio_ignora_falsos_positivos():
    contas = [_conta("1001", "sem_comunicacao"), _conta("2002", "falso_positivo")]
    texto = alerting.montar_relatorio_sem_comunicacao(contas, agora=AGORA)
    assert "1001" in texto
    assert "2002" not in texto


def test_relatorio_escapa_html_no_nome():
    contas = [_conta("1001", "sem_comunicacao", nome="Cliente <script>")]
    texto = alerting.montar_relatorio_sem_comunicacao(contas, agora=AGORA)
    assert "<script>" not in texto
    assert "&lt;script&gt;" in texto


def test_mensagem_normalizacao_contem_horario():
    texto = alerting.montar_mensagem_normalizacao(AGORA)
    assert "Normalizado" in texto
    assert "12:00" in texto


def test_processar_alertas_nao_envia_quando_sem_mudanca(app):
    cycle = CollectionCycle(status="success", source="scheduled")
    db.session.add(cycle)
    db.session.flush()

    telegram = FakeTelegramClient()
    resultado = alerting.processar_alertas(
        cycle=cycle,
        contas_atuais=[_conta("1001", "sem_comunicacao")],
        contas_anteriores_sem_comunicacao=["1001"],
        telegram_client=telegram,
        agora=AGORA,
    )

    assert resultado is None
    assert telegram.mensagens == []
    assert AlertSent.query.count() == 0


def test_processar_alertas_envia_quando_entra_conta(app):
    cycle = CollectionCycle(status="success", source="scheduled")
    db.session.add(cycle)
    db.session.flush()

    telegram = FakeTelegramClient()
    resultado = alerting.processar_alertas(
        cycle=cycle,
        contas_atuais=[_conta("1001", "sem_comunicacao")],
        contas_anteriores_sem_comunicacao=[],
        telegram_client=telegram,
        agora=AGORA,
    )

    assert resultado is not None
    assert resultado.message_type == "entrada"
    assert resultado.success is True
    assert resultado.accounts_added == ["1001"]
    assert len(telegram.mensagens) == 1


def test_processar_alertas_normalizacao_quando_lista_esvazia(app):
    cycle = CollectionCycle(status="success", source="scheduled")
    db.session.add(cycle)
    db.session.flush()

    telegram = FakeTelegramClient()
    resultado = alerting.processar_alertas(
        cycle=cycle,
        contas_atuais=[_conta("1001", "falso_positivo")],
        contas_anteriores_sem_comunicacao=["1001"],
        telegram_client=telegram,
        agora=AGORA,
    )

    assert resultado.message_type == "normalizacao"
    assert "Normalizado" in telegram.mensagens[0]


def test_processar_alertas_marca_sucesso_falso_quando_telegram_nao_configurado(app):
    cycle = CollectionCycle(status="success", source="scheduled")
    db.session.add(cycle)
    db.session.flush()

    resultado = alerting.processar_alertas(
        cycle=cycle,
        contas_atuais=[_conta("1001", "sem_comunicacao")],
        contas_anteriores_sem_comunicacao=[],
        telegram_client=None,
        agora=AGORA,
    )

    assert resultado.success is False
    assert resultado.telegram_message_id is None
