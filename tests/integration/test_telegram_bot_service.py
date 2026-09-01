import pytest

from app.integrations.softguard_client import SoftGuardAuthError, SoftGuardError
from app.models.audit import AuditLog
from app.services import settings_service
from app.services import telegram_bot_service as svc

CONTAS = [
    {"cue_ncuenta": "0095", "cue_iid": "9516", "cue_cnombre": "AUTO MECANICA CENTRO"},
    {"cue_ncuenta": "0010", "cue_iid": "9530", "cue_cnombre": "VILLEFORT HM"},
    {"cue_ncuenta": "0011", "cue_iid": "9531", "cue_cnombre": "VILLEFORT HM DEPOSITO"},
]

# Formato do export nativo: cabeçalho + uma linha por evento.
EXPORT_HTML = (
    b"<table>"
    b"<tr><th>Data e hora do evento</th><th>Evento</th></tr>"
    b"<tr><td>01/09 08:22:01</td><td>CLO - Alarme Armado</td></tr>"
    b"<tr><td>01/09 07:05:55</td><td>OPN - Alarme Desarmado</td></tr>"
    b"<tr><td>&nbsp;</td><td></td></tr>"
    b"</table>"
)

ZONAS = [
    {"zon_ccodigo": "1  ", "zon_cdescripcion": "MAG PORTA SALA", "zon_cAlarmaAGenerar": "NYR"},
    {"zon_ccodigo": "SP1", "zon_cdescripcion": "SENTINELLA: SOS", "zon_cAlarmaAGenerar": ""},
]


class FakeTelegram:
    def __init__(self):
        self.mensagens = []  # (chat_id, texto)
        self.documentos = []  # (chat_id, nome_arquivo, legenda)

    def enviar_mensagem(self, texto, *, chat_id=None):
        self.mensagens.append((chat_id, texto))
        return ["1"]

    def enviar_documento(self, conteudo, *, nome_arquivo, chat_id=None, legenda=""):
        self.documentos.append((chat_id, nome_arquivo, legenda, conteudo))
        return "2"

    @property
    def texto_completo(self):
        return "\n".join(t for _, t in self.mensagens)


class FakeSoftGuard:
    def __init__(self, *, erro=None):
        self.erro = erro
        self.zonas_pedidas = []
        self.historicos = 0
        self.exports = 0

    def listar_todas_contas(self, **kwargs):
        return CONTAS

    def listar_zonas(self, cue_iid, **kwargs):
        if self.erro:
            raise self.erro
        self.zonas_pedidas.append(cue_iid)
        return ZONAS

    def buscar_historico(self, **kwargs):
        # Não deve ser usado pelo /relatorio: não filtra por conta.
        if self.erro:
            raise self.erro
        self.historicos += 1
        return [{"rec_iid": "1"}, {"rec_iid": "2"}]

    def exportar_historico_html(self, **kwargs):
        if self.erro:
            raise self.erro
        self.exports += 1
        return EXPORT_HTML


class SessaoFake:
    """Mesma interface de `_SessaoSoftGuard`, sem rede."""

    def __init__(self, client):
        self._client = client
        self.invalidada = False

    def client(self):
        return self._client

    def mapa_contas(self):
        from app.domain import tecnico as dom_tecnico

        return dom_tecnico.mapa_contas(CONTAS)

    def invalidar(self):
        self.invalidada = True


def _update(texto, *, user_id=111, chat_id="-100999", update_id=1):
    return {
        "update_id": update_id,
        "message": {
            "chat": {"id": chat_id},
            "from": {"id": user_id, "first_name": "Tecnico"},
            "text": texto,
        },
    }


@pytest.fixture(autouse=True)
def _limpar_cooldown():
    svc.limpar_cooldowns()
    yield
    svc.limpar_cooldowns()


@pytest.fixture
def autorizado(app):
    settings_service.set("bot_tecnicos_ids", "111")
    settings_service.set("bot_cooldown_segundos", "0")
    return 111


def _processar(app, texto, *, sessao=None, telegram=None, user_id=111):
    telegram = telegram or FakeTelegram()
    sessao = sessao or SessaoFake(FakeSoftGuard())
    svc.processar_update(
        _update(texto, user_id=user_id), config=app.config, sessao=sessao, telegram=telegram
    )
    return telegram, sessao


# ---------- autorização ----------


def test_id_fora_da_lista_e_negado_e_auditado(app):
    settings_service.set("bot_tecnicos_ids", "111")
    telegram, sessao = _processar(app, "/zona 95", user_id=999)

    assert "Sem permissão" in telegram.texto_completo
    assert sessao.client().zonas_pedidas == []
    entrada = AuditLog.query.filter_by(action="bot_pedido_negado").one()
    assert entrada.result == "failure"
    assert entrada.details["telegram_user_id"] == 999


def test_sem_lista_configurada_ninguem_e_atendido(app):
    """Padrão fechado: enquanto o admin não autorizar ninguém, o bot não
    entrega dado sensível a ninguém."""
    telegram, _ = _processar(app, "/zona 95")
    assert "Sem permissão" in telegram.texto_completo


def test_autoriza_por_quem_enviou_nao_pelo_grupo(app, autorizado):
    """Estar num grupo autorizado não basta — alguém pode ser adicionado
    ao grupo."""
    telegram = FakeTelegram()
    sessao = SessaoFake(FakeSoftGuard())
    svc.processar_update(
        _update("/zona 95", user_id=222, chat_id="-100999"),
        config=app.config, sessao=sessao, telegram=telegram,
    )
    assert "Sem permissão" in telegram.texto_completo


def test_texto_solto_nao_gera_resposta_nem_auditoria(app, autorizado):
    telegram, _ = _processar(app, "bom dia pessoal")
    assert telegram.mensagens == []
    assert AuditLog.query.count() == 0


# ---------- /zona ----------


def test_zona_responde_zoneamento_formatado(app, autorizado):
    telegram, sessao = _processar(app, "/zona 95")

    assert sessao.client().zonas_pedidas == ["9516"]
    assert "MAG PORTA SALA" in telegram.texto_completo
    assert "Uso interno" in telegram.texto_completo
    entrada = AuditLog.query.filter_by(action="bot_zona_pedido").one()
    assert entrada.result == "success"
    assert entrada.details["conta"] == "95"


def test_auditoria_nao_guarda_o_zoneamento(app, autorizado):
    _processar(app, "/zona 95")
    detalhes = str(AuditLog.query.filter_by(action="bot_zona_pedido").one().details)
    assert "MAG PORTA SALA" not in detalhes


def test_zona_por_nome(app, autorizado):
    telegram, sessao = _processar(app, "/zona auto mecanica")
    assert sessao.client().zonas_pedidas == ["9516"]


def test_zona_com_nome_ambiguo_pede_o_numero(app, autorizado):
    telegram, sessao = _processar(app, "/zona villefort")
    assert sessao.client().zonas_pedidas == []  # não chutou nenhuma conta
    assert "Repita com o número" in telegram.texto_completo


def test_zona_sem_argumento_avisa(app, autorizado):
    telegram, sessao = _processar(app, "/zona")
    assert "Faltou a conta" in telegram.texto_completo
    assert sessao.client().zonas_pedidas == []


def test_conta_inexistente_avisa(app, autorizado):
    telegram, _ = _processar(app, "/zona 77777")
    assert "Não achei" in telegram.texto_completo


# ---------- /relatorio ----------


def test_relatorio_envia_documento_com_resumo(app, autorizado):
    telegram, sessao = _processar(app, "/relatorio 95")

    assert sessao.client().exports == 1
    chat_id, nome_arquivo, legenda, conteudo = telegram.documentos[0]
    assert nome_arquivo.startswith("0095_")
    assert "2 evento(s)" in legenda  # do próprio arquivo, sem contar cabeçalho/vazias
    assert conteudo == EXPORT_HTML
    assert AuditLog.query.filter_by(action="bot_relatorio_pedido").one().result == "success"


def test_relatorio_nao_usa_buscar_historico(app, autorizado):
    """Regressão: `buscar_historico` não filtra por conta — usá-lo aqui
    puxava o histórico da base inteira só para contar os eventos de uma
    loja (lento a ponto de estourar, e com o número errado)."""
    telegram, sessao = _processar(app, "/relatorio 95")
    assert sessao.client().historicos == 0


def test_export_recusado_avisa_que_e_permissao(app, autorizado):
    """Repetir não resolve: o técnico precisa saber que é permissão."""
    erro = SoftGuardError("A PowerCentral recusou o export do histórico (...)")
    sessao = SessaoFake(FakeSoftGuard(erro=erro))
    telegram, _ = _processar(app, "/relatorio 95", sessao=sessao)

    assert "permissão" in telegram.texto_completo
    assert "Tente de novo" not in telegram.texto_completo


def test_relatorio_aceita_dias(app, autorizado):
    telegram, _ = _processar(app, "/relatorio 95 15")
    assert "15 dia(s)" in telegram.documentos[0][2]


def test_relatorio_usa_dias_padrao_configurado(app, autorizado):
    settings_service.set("bot_relatorio_dias_padrao", "3")
    telegram, _ = _processar(app, "/relatorio 95")
    assert "3 dia(s)" in telegram.documentos[0][2]


# ---------- /ajuda e cooldown ----------


def test_ajuda_nao_consome_cooldown(app, autorizado):
    settings_service.set("bot_cooldown_segundos", "60")
    telegram = FakeTelegram()
    sessao = SessaoFake(FakeSoftGuard())
    _processar(app, "/ajuda", telegram=telegram, sessao=sessao)
    _processar(app, "/zona 95", telegram=telegram, sessao=sessao)
    assert sessao.client().zonas_pedidas == ["9516"]


def test_cooldown_barra_o_segundo_pedido_seguido(app, autorizado):
    settings_service.set("bot_cooldown_segundos", "60")
    telegram = FakeTelegram()
    sessao = SessaoFake(FakeSoftGuard())
    _processar(app, "/zona 95", telegram=telegram, sessao=sessao)
    _processar(app, "/zona 10", telegram=telegram, sessao=sessao)

    assert sessao.client().zonas_pedidas == ["9516"]  # o segundo não rodou
    assert "tente de novo em" in telegram.texto_completo


def test_cooldown_e_por_usuario(app):
    settings_service.set("bot_tecnicos_ids", "111,222")
    settings_service.set("bot_cooldown_segundos", "60")
    sessao = SessaoFake(FakeSoftGuard())
    _processar(app, "/zona 95", sessao=sessao, user_id=111)
    _processar(app, "/zona 10", sessao=sessao, user_id=222)
    assert sessao.client().zonas_pedidas == ["9516", "9530"]


# ---------- resiliência ----------


def test_portal_fora_do_ar_vira_resposta_e_auditoria_de_falha(app, autorizado):
    sessao = SessaoFake(FakeSoftGuard(erro=SoftGuardError("portal fora")))
    telegram, _ = _processar(app, "/zona 95", sessao=sessao)

    assert "não respondeu" in telegram.texto_completo
    assert AuditLog.query.filter_by(action="bot_zona_pedido").one().result == "failure"


def test_sessao_expirada_invalida_o_cache_e_pede_pra_repetir(app, autorizado):
    sessao = SessaoFake(FakeSoftGuard(erro=SoftGuardAuthError("expirou")))
    telegram, sessao = _processar(app, "/zona 95", sessao=sessao)

    assert sessao.invalidada is True
    assert "Tente de novo" in telegram.texto_completo


# ---------- loop de long polling ----------


class TelegramComUpdates(FakeTelegram):
    def __init__(self, lotes):
        super().__init__()
        self._lotes = list(lotes)
        self.offsets = []

    def buscar_updates(self, *, offset=None, timeout=25):
        self.offsets.append(offset)
        return self._lotes.pop(0) if self._lotes else []


def _preparar_loop(app, monkeypatch, telegram, *, ativado=True):
    # `_uma_volta` abre um app context próprio (é o que o worker faz), e
    # isso significa sessão nova — a configuração precisa estar commitada
    # para ele enxergar.
    from app.extensions import db
    from app.services import collector

    settings_service.set("bot_ativado", "true" if ativado else "false")
    settings_service.set("bot_tecnicos_ids", "111")
    settings_service.set("bot_cooldown_segundos", "0")
    db.session.commit()

    monkeypatch.setattr(collector, "criar_cliente_telegram", lambda config: telegram)
    monkeypatch.setattr(svc, "_SessaoSoftGuard", lambda config: SessaoFake(FakeSoftGuard()))


def test_loop_desligado_nao_consulta_o_telegram(app, monkeypatch):
    telegram = TelegramComUpdates([])
    _preparar_loop(app, monkeypatch, telegram, ativado=False)

    espera = svc._uma_volta(app, sessao_ref={})

    assert telegram.offsets == []
    assert espera == svc.PAUSA_OCIOSA_SEGUNDOS


def test_ao_ligar_descarta_a_fila_sem_executar(app, monkeypatch):
    """Comando parado há horas não pode disparar todo de uma vez quando
    alguém liga o bot na tela (o Telegram guarda os updates ~24h)."""
    antigo = _update("/zona 95", update_id=40)
    telegram = TelegramComUpdates([[antigo], []])
    _preparar_loop(app, monkeypatch, telegram)

    svc._uma_volta(app, sessao_ref={"ativo": False, "softguard": None})

    assert telegram.documentos == [] and telegram.mensagens == []
    assert settings_service.get_bot_update_offset() == 41


def test_loop_processa_e_avanca_o_offset(app, monkeypatch):
    telegram = TelegramComUpdates([[_update("/ajuda", update_id=7)]])
    _preparar_loop(app, monkeypatch, telegram)

    svc._uma_volta(app, sessao_ref={"ativo": True, "softguard": SessaoFake(FakeSoftGuard())})

    assert "/relatorio" in telegram.texto_completo  # respondeu a ajuda
    assert settings_service.get_bot_update_offset() == 8


def test_erro_em_um_comando_nao_derruba_o_loop(app, monkeypatch):
    """Aceite §9: exceção tratando um update é registrada e o loop segue
    para o próximo."""
    class SessaoQueQuebra(SessaoFake):
        def mapa_contas(self):
            raise RuntimeError("falha inesperada")

    telegram = TelegramComUpdates(
        [[_update("/zona 95", update_id=1), _update("/ajuda", update_id=2)]]
    )
    _preparar_loop(app, monkeypatch, telegram)

    svc._uma_volta(
        app, sessao_ref={"ativo": True, "softguard": SessaoQueQuebra(FakeSoftGuard())}
    )

    # o segundo update foi processado mesmo com o primeiro estourando
    assert "/relatorio" in telegram.texto_completo
    assert settings_service.get_bot_update_offset() == 3


def test_falha_do_telegram_nao_derruba_o_loop(app, monkeypatch):
    from app.integrations.telegram_client import TelegramError

    class TelegramQuebrado(FakeTelegram):
        def buscar_updates(self, *, offset=None, timeout=25):
            raise TelegramError("api fora")

    telegram = TelegramQuebrado()
    _preparar_loop(app, monkeypatch, telegram)

    espera = svc._uma_volta(app, sessao_ref={"ativo": True, "softguard": None})

    assert espera == svc.PAUSA_ERRO_SEGUNDOS
