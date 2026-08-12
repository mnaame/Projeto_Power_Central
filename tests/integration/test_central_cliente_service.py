from cryptography.fernet import Fernet

from app.extensions import db
from app.integrations.auvo_painel_client import (
    CentralClienteCookieExpiradoError,
    CentralClientePainelError,
    PainelCredentials,
)
from app.models.audit import AuditLog
from app.models.auvo import AuvoDepara
from app.models.central_cliente import CentralClienteLink, CentralClienteLote
from app.services import central_cliente_service as svc
from app.services import settings_service


def _depara(conta, id_auvo, *, status="OK", score=0.9, nome="CLIENTE"):
    linha = AuvoDepara(conta_power=conta, nome_power=nome, id_auvo=id_auvo, status=status, score=score)
    db.session.add(linha)
    db.session.commit()
    return linha


class FakePainelClient:
    def __init__(self, respostas=None, falhas=None):
        self.chamadas = []
        self._respostas = respostas or {}
        self._falhas = falhas or {}

    def criar_contato_link(self, *, codigo_cliente, **kwargs):
        self.chamadas.append({"codigo_cliente": codigo_cliente, **kwargs})
        if codigo_cliente in self._falhas:
            raise self._falhas[codigo_cliente]
        return self._respostas.get(codigo_cliente, codigo_cliente * 1000)


def _sem_pausa(_segundos):
    pass


class FakeAuvoClient:
    """Fake da API OFICIAL (AuvoClient), usada só para buscar telefone."""

    def __init__(self, clientes=None, falha=False):
        self._clientes = clientes or []
        self._falha = falha

    def listar_clientes(self):
        if self._falha:
            from app.integrations.auvo_client import AuvoError

            raise AuvoError("falha simulada")
        return self._clientes


# ---------- montar_lote ----------


def test_montar_lote_inclui_ok_com_score_alto(app):
    _depara("95", 111, status="OK", score=0.9)
    candidatos = svc.montar_lote(score_minimo=0.70)
    assert [c["id_auvo"] for c in candidatos] == [111]
    assert candidatos[0]["manual"] is False


def test_montar_lote_exclui_score_baixo_sem_marcacao(app):
    _depara("95", 111, status="OK", score=0.5)
    assert svc.montar_lote(score_minimo=0.70) == []


def test_montar_lote_exclui_revisar_sem_marcacao(app):
    _depara("95", 111, status="REVISAR", score=0.95)
    assert svc.montar_lote(score_minimo=0.70) == []


def test_montar_lote_inclui_marcado_manualmente(app):
    _depara("95", 111, status="REVISAR", score=0.5)
    candidatos = svc.montar_lote(score_minimo=0.70, ids_extra=[111])
    assert [c["id_auvo"] for c in candidatos] == [111]
    assert candidatos[0]["manual"] is True


def test_montar_lote_dedup_por_id_auvo(app):
    _depara("95", 111, status="OK", score=0.9, nome="LOJA CENTRO")
    _depara("96", 111, status="OK", score=0.9, nome="TESOURARIA CENTRO")
    candidatos = svc.montar_lote(score_minimo=0.70)
    assert len(candidatos) == 1


def test_montar_lote_exclui_ja_criado_em_lote_real(app):
    lote = CentralClienteLote(simulacao=False, status="running", total_itens=1)
    db.session.add(lote)
    db.session.flush()
    db.session.add(CentralClienteLink(lote_id=lote.id, id_auvo=111, nome="X", status="criado"))
    db.session.commit()

    _depara("95", 111, status="OK", score=0.9)
    assert svc.montar_lote(score_minimo=0.70) == []


def test_montar_lote_nao_exclui_criado_em_simulacao(app):
    """Simular não pode ter efeito nenhum sobre o que ainda pode ser
    rodado de verdade — um 'criado' de lote em simulação não é link real
    nenhum, é só um registro do que SERIA criado."""
    lote = CentralClienteLote(simulacao=True, status="running", total_itens=1)
    db.session.add(lote)
    db.session.flush()
    db.session.add(CentralClienteLink(lote_id=lote.id, id_auvo=111, nome="X", status="criado"))
    db.session.commit()

    _depara("95", 111, status="OK", score=0.9)
    candidatos = svc.montar_lote(score_minimo=0.70)
    assert [c["id_auvo"] for c in candidatos] == [111]


def test_montar_lote_permite_retentar_apos_falha(app):
    lote = CentralClienteLote(simulacao=True, status="error", total_itens=1)
    db.session.add(lote)
    db.session.flush()
    db.session.add(CentralClienteLink(lote_id=lote.id, id_auvo=111, nome="X", status="erro"))
    db.session.commit()

    _depara("95", 111, status="OK", score=0.9)
    candidatos = svc.montar_lote(score_minimo=0.70)
    assert [c["id_auvo"] for c in candidatos] == [111]


# ---------- criar_lote ----------


def test_criar_lote_vazio_levanta_erro(app):
    try:
        svc.criar_lote([], simulacao=True, user_id=None)
        assert False, "deveria ter levantado CentralClienteLoteVazioError"
    except svc.CentralClienteLoteVazioError:
        pass


def test_criar_lote_persiste_itens_pendentes(app):
    lote = svc.criar_lote(
        [{"id_auvo": 111, "nome": "CLIENTE X"}], simulacao=True, user_id=None
    )
    assert lote.status == "running"
    assert lote.total_itens == 1
    assert len(lote.itens) == 1
    assert lote.itens[0].status == "pendente"
    assert lote.itens[0].id_auvo == 111


# ---------- executar_lote: simulação ----------


def test_executar_lote_simulacao_nao_chama_painel(app):
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "CLIENTE X"}], simulacao=True, user_id=None)
    resultado = svc.executar_lote(lote, credentials=None, config=app.config, sleep_fn=_sem_pausa)

    assert resultado.status == "success"
    assert resultado.total_sucesso == 1
    assert resultado.total_falha == 0
    item = resultado.itens[0]
    assert item.status == "criado"
    assert item.link_url.startswith("https://novomillenium.auvo.com.br/share/")


def test_executar_lote_simulacao_nao_gera_senha_por_padrao(app):
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "CLIENTE X"}], simulacao=True, user_id=None)
    resultado = svc.executar_lote(lote, credentials=None, config=app.config, sleep_fn=_sem_pausa)
    assert resultado.itens[0].login is None
    assert resultado.itens[0].senha_cifrada is None


def test_executar_lote_com_gerar_login_senha_ligado_cifra_a_senha(app):
    settings_service.set("central_gerar_login_senha", "true")
    db.session.commit()
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "CLIENTE X"}], simulacao=True, user_id=None)
    resultado = svc.executar_lote(lote, credentials=None, config=app.config, sleep_fn=_sem_pausa)

    item = resultado.itens[0]
    assert item.login == "cliente111"
    assert item.senha_cifrada is not None
    fernet = Fernet(app.config["ENCRYPTION_KEY"])
    senha_decifrada = fernet.decrypt(item.senha_cifrada.encode()).decode()
    assert len(senha_decifrada) >= 8


# ---------- executar_lote: produção ----------


def test_executar_lote_producao_chama_painel_com_pausa(app):
    lote = svc.criar_lote(
        [{"id_auvo": 111, "nome": "CLIENTE X"}, {"id_auvo": 222, "nome": "CLIENTE Y"}],
        simulacao=False,
        user_id=None,
    )
    fake = FakePainelClient()
    pausas = []
    resultado = svc.executar_lote(
        lote,
        credentials=PainelCredentials(cookie="abc", auvo_user_request="1"),
        config=app.config,
        client=fake,
        sleep_fn=lambda s: pausas.append(s),
    )

    assert resultado.status == "success"
    assert resultado.total_sucesso == 2
    assert len(fake.chamadas) == 2
    assert pausas == [1.0, 1.0]  # padrão central_pausa_segundos
    assert resultado.itens[0].contato_codigo == 111000


def test_executar_lote_producao_audita_cada_criacao(app):
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "CLIENTE X"}], simulacao=False, user_id=None)
    fake = FakePainelClient()
    svc.executar_lote(
        lote,
        credentials=PainelCredentials(cookie="abc", auvo_user_request="1"),
        config=app.config,
        client=fake,
        sleep_fn=_sem_pausa,
    )
    entrada = AuditLog.query.filter_by(action="central_link_criado").first()
    assert entrada is not None
    assert entrada.details["id_auvo"] == 111
    assert entrada.details["contato_codigo"] == 111000


def test_executar_lote_falha_isolada_nao_derruba_os_demais(app):
    lote = svc.criar_lote(
        [{"id_auvo": 111, "nome": "CLIENTE X"}, {"id_auvo": 222, "nome": "CLIENTE Y"}],
        simulacao=False,
        user_id=None,
    )
    fake = FakePainelClient(falhas={111: CentralClientePainelError("recusado")})
    resultado = svc.executar_lote(
        lote,
        credentials=PainelCredentials(cookie="abc", auvo_user_request="1"),
        config=app.config,
        client=fake,
        sleep_fn=_sem_pausa,
    )

    assert resultado.status == "parcial"
    assert resultado.total_sucesso == 1
    assert resultado.total_falha == 1
    item_falho = next(i for i in resultado.itens if i.id_auvo == 111)
    assert item_falho.status == "erro"
    item_ok = next(i for i in resultado.itens if i.id_auvo == 222)
    assert item_ok.status == "criado"


def test_executar_lote_cookie_expirado_aborta_o_resto(app):
    lote = svc.criar_lote(
        [{"id_auvo": 111, "nome": "CLIENTE X"}, {"id_auvo": 222, "nome": "CLIENTE Y"}],
        simulacao=False,
        user_id=None,
    )
    fake = FakePainelClient(falhas={111: CentralClienteCookieExpiradoError("vencido")})
    resultado = svc.executar_lote(
        lote,
        credentials=PainelCredentials(cookie="abc", auvo_user_request="1"),
        config=app.config,
        client=fake,
        sleep_fn=_sem_pausa,
    )

    assert resultado.status == "error"
    assert resultado.erro_mensagem
    item1 = next(i for i in resultado.itens if i.id_auvo == 111)
    item2 = next(i for i in resultado.itens if i.id_auvo == 222)
    # abortado: nada a partir do item com cookie vencido foi sequer tentado
    assert item1.status == "pendente"
    assert item2.status == "pendente"
    assert len(fake.chamadas) == 1


def test_executar_lote_sem_credenciais_marca_erro(app):
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "CLIENTE X"}], simulacao=False, user_id=None)
    resultado = svc.executar_lote(lote, credentials=None, config=app.config, sleep_fn=_sem_pausa)
    assert resultado.status == "error"
    assert resultado.itens[0].status == "erro"


def test_executar_lote_bloqueia_execucao_concorrente(app):
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "CLIENTE X"}], simulacao=True, user_id=None)
    assert svc._tentar_iniciar(lote.id) is True
    try:
        try:
            svc.executar_lote(lote, credentials=None, config=app.config, sleep_fn=_sem_pausa)
            assert False, "deveria ter levantado CentralClienteLoteEmAndamentoError"
        except svc.CentralClienteLoteEmAndamentoError:
            pass
    finally:
        svc._finalizar(lote.id)


# ---------- telefone (API oficial) + WhatsApp ----------


def test_executar_lote_popula_telefones_normalizados(app):
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "CLIENTE X"}], simulacao=True, user_id=None)
    fake_auvo = FakeAuvoClient(clientes=[{"id": 111, "phoneNumber": "(31) 99999-8888"}])
    resultado = svc.executar_lote(
        lote, credentials=None, config=app.config, auvo_client=fake_auvo, sleep_fn=_sem_pausa
    )
    assert resultado.itens[0].telefones == ["5531999998888"]


def test_executar_lote_sem_telefone_na_auvo_fica_none(app):
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "CLIENTE X"}], simulacao=True, user_id=None)
    fake_auvo = FakeAuvoClient(clientes=[{"id": 222, "phoneNumber": "31999998888"}])
    resultado = svc.executar_lote(
        lote, credentials=None, config=app.config, auvo_client=fake_auvo, sleep_fn=_sem_pausa
    )
    assert resultado.itens[0].telefones is None


def test_executar_lote_telefone_como_lista_mantem_todos(app):
    """`phoneNumber` na API oficial vem como lista (confirmado em produção
    com um cliente de 2 números) — guarda todos os válidos, pra tela
    deixar escolher pra qual número mandar."""
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "CLIENTE X"}], simulacao=True, user_id=None)
    fake_auvo = FakeAuvoClient(
        clientes=[{"id": 111, "phoneNumber": ["31995222809", "31996837126"]}]
    )
    resultado = svc.executar_lote(
        lote, credentials=None, config=app.config, auvo_client=fake_auvo, sleep_fn=_sem_pausa
    )
    assert resultado.itens[0].telefones == ["5531995222809", "5531996837126"]


def test_executar_lote_telefone_lista_de_um_item(app):
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "CLIENTE X"}], simulacao=True, user_id=None)
    fake_auvo = FakeAuvoClient(clientes=[{"id": 111, "phoneNumber": ["31999998888"]}])
    resultado = svc.executar_lote(
        lote, credentials=None, config=app.config, auvo_client=fake_auvo, sleep_fn=_sem_pausa
    )
    assert resultado.itens[0].telefones == ["5531999998888"]


def test_executar_lote_telefones_repetidos_nao_duplica(app):
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "CLIENTE X"}], simulacao=True, user_id=None)
    fake_auvo = FakeAuvoClient(
        clientes=[{"id": 111, "phoneNumber": ["31999998888", "(31) 99999-8888"]}]
    )
    resultado = svc.executar_lote(
        lote, credentials=None, config=app.config, auvo_client=fake_auvo, sleep_fn=_sem_pausa
    )
    assert resultado.itens[0].telefones == ["5531999998888"]


def test_executar_lote_telefone_lista_vazia_fica_none(app):
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "CLIENTE X"}], simulacao=True, user_id=None)
    fake_auvo = FakeAuvoClient(clientes=[{"id": 111, "phoneNumber": []}])
    resultado = svc.executar_lote(
        lote, credentials=None, config=app.config, auvo_client=fake_auvo, sleep_fn=_sem_pausa
    )
    assert resultado.itens[0].telefones is None


def test_executar_lote_telefone_invalido_fica_none(app):
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "CLIENTE X"}], simulacao=True, user_id=None)
    fake_auvo = FakeAuvoClient(clientes=[{"id": 111, "phoneNumber": "123"}])
    resultado = svc.executar_lote(
        lote, credentials=None, config=app.config, auvo_client=fake_auvo, sleep_fn=_sem_pausa
    )
    assert resultado.itens[0].telefones is None


def test_executar_lote_falha_ao_buscar_telefone_nao_derruba_o_lote(app):
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "CLIENTE X"}], simulacao=True, user_id=None)
    fake_auvo = FakeAuvoClient(falha=True)
    resultado = svc.executar_lote(
        lote, credentials=None, config=app.config, auvo_client=fake_auvo, sleep_fn=_sem_pausa
    )
    assert resultado.status == "success"
    assert resultado.itens[0].telefones is None


def test_renderizar_mensagem_whatsapp_substitui_placeholders(app):
    mensagem = svc.renderizar_mensagem_whatsapp(nome="Maria", link="https://x/y")
    assert "Maria" in mensagem
    assert "https://x/y" in mensagem


def test_renderizar_mensagem_whatsapp_placeholder_desconhecido_fica_literal(app):
    settings_service.set("central_whatsapp_template", "Oi {nome}, {campo_que_nao_existe}")
    db.session.commit()
    mensagem = svc.renderizar_mensagem_whatsapp(nome="Maria", link="https://x/y")
    assert mensagem == "Oi Maria, {campo_que_nao_existe}"


def test_montar_link_whatsapp_item_sem_telefone_devolve_none(app):
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "CLIENTE X"}], simulacao=True, user_id=None)
    resultado = svc.executar_lote(lote, credentials=None, config=app.config, sleep_fn=_sem_pausa)
    item = resultado.itens[0]
    assert svc.montar_link_whatsapp_item(item, telefone="5531999998888", config=app.config) is None


def test_montar_link_whatsapp_item_com_telefone(app):
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "CLIENTE X"}], simulacao=True, user_id=None)
    fake_auvo = FakeAuvoClient(clientes=[{"id": 111, "phoneNumber": "31999998888"}])
    resultado = svc.executar_lote(
        lote, credentials=None, config=app.config, auvo_client=fake_auvo, sleep_fn=_sem_pausa
    )
    item = resultado.itens[0]
    link = svc.montar_link_whatsapp_item(item, telefone="5531999998888", config=app.config)
    assert link.startswith("https://wa.me/5531999998888?text=")
    assert "CLIENTE" in link or "CLIENTE".lower() in link.lower()


def test_montar_link_whatsapp_item_telefone_que_nao_e_do_item_devolve_none(app):
    """Nunca abre num número arbitrário — só nos que vieram da Auvo pra
    aquele cliente especificamente."""
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "CLIENTE X"}], simulacao=True, user_id=None)
    fake_auvo = FakeAuvoClient(clientes=[{"id": 111, "phoneNumber": "31999998888"}])
    resultado = svc.executar_lote(
        lote, credentials=None, config=app.config, auvo_client=fake_auvo, sleep_fn=_sem_pausa
    )
    item = resultado.itens[0]
    assert svc.montar_link_whatsapp_item(item, telefone="5511900000000", config=app.config) is None


def test_montar_link_whatsapp_item_escolhe_qualquer_telefone_da_lista(app):
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "CLIENTE X"}], simulacao=True, user_id=None)
    fake_auvo = FakeAuvoClient(
        clientes=[{"id": 111, "phoneNumber": ["31995222809", "31996837126"]}]
    )
    resultado = svc.executar_lote(
        lote, credentials=None, config=app.config, auvo_client=fake_auvo, sleep_fn=_sem_pausa
    )
    item = resultado.itens[0]
    assert item.telefones == ["5531995222809", "5531996837126"]
    link = svc.montar_link_whatsapp_item(item, telefone="5531996837126", config=app.config)
    assert link.startswith("https://wa.me/5531996837126?text=")


def test_montar_link_whatsapp_item_com_senha_decifra_para_a_mensagem(app):
    from urllib.parse import unquote, urlparse, parse_qs

    settings_service.set("central_gerar_login_senha", "true")
    settings_service.set("central_whatsapp_template", "{nome} login={login} senha={senha}")
    db.session.commit()
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "CLIENTE X"}], simulacao=True, user_id=None)
    fake_auvo = FakeAuvoClient(clientes=[{"id": 111, "phoneNumber": "31999998888"}])
    resultado = svc.executar_lote(
        lote, credentials=None, config=app.config, auvo_client=fake_auvo, sleep_fn=_sem_pausa
    )
    item = resultado.itens[0]
    assert item.login == "cliente111"

    fernet = Fernet(app.config["ENCRYPTION_KEY"])
    senha_esperada = fernet.decrypt(item.senha_cifrada.encode()).decode()

    link = svc.montar_link_whatsapp_item(item, telefone="5531999998888", config=app.config)
    texto = unquote(parse_qs(urlparse(link).query)["text"][0])
    assert texto == f"CLIENTE X login=cliente111 senha={senha_esperada}"


# ---------- buscar_clientes ----------


def test_buscar_clientes_termo_vazio_devolve_vazio(app):
    assert svc.buscar_clientes("") == []
    assert svc.buscar_clientes("   ") == []


def test_buscar_clientes_por_nome(app):
    _depara("95", 111, nome="AUTO MECANICA CENTRO")
    _depara("96", 222, nome="OUTRA LOJA")
    resultados = svc.buscar_clientes("auto mecanica")
    assert [r["id_auvo"] for r in resultados] == [111]


def test_buscar_clientes_por_id_auvo(app):
    _depara("95", 111, nome="AUTO MECANICA")
    resultados = svc.buscar_clientes("111")
    assert [r["id_auvo"] for r in resultados] == [111]


def test_buscar_clientes_por_conta(app):
    _depara("95", 111, nome="AUTO MECANICA")
    resultados = svc.buscar_clientes("95")
    assert [r["id_auvo"] for r in resultados] == [111]


def test_buscar_clientes_sem_resultado(app):
    assert svc.buscar_clientes("nao existe nenhum cliente assim") == []


def test_buscar_clientes_mostra_link_existente_de_producao(app):
    _depara("95", 111, nome="AUTO MECANICA")
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "AUTO MECANICA"}], simulacao=False, user_id=None)
    svc.executar_lote(
        lote,
        credentials=PainelCredentials(cookie="x", auvo_user_request="1"),
        config=app.config,
        client=FakePainelClient(),
        sleep_fn=_sem_pausa,
    )

    resultados = svc.buscar_clientes("111")
    assert len(resultados) == 1
    link_existente = resultados[0]["link_existente"]
    assert link_existente is not None
    assert link_existente.lote.simulacao is False


def test_buscar_clientes_mostra_link_existente_de_simulacao(app):
    _depara("95", 111, nome="AUTO MECANICA")
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "AUTO MECANICA"}], simulacao=True, user_id=None)
    svc.executar_lote(lote, credentials=None, config=app.config, sleep_fn=_sem_pausa)

    resultados = svc.buscar_clientes("111")
    link_existente = resultados[0]["link_existente"]
    assert link_existente is not None
    assert link_existente.lote.simulacao is True


def test_buscar_clientes_sem_link_devolve_none(app):
    _depara("95", 111, nome="AUTO MECANICA")
    resultados = svc.buscar_clientes("111")
    assert resultados[0]["link_existente"] is None


# ---------- remover_link ----------


def test_remover_link_marca_removido_e_audita(app):
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "AUTO MECANICA"}], simulacao=True, user_id=None)
    svc.executar_lote(lote, credentials=None, config=app.config, sleep_fn=_sem_pausa)
    item = lote.itens[0]
    assert item.status == "criado"

    svc.remover_link(item)
    db.session.commit()

    assert item.status == "removido"
    entrada = AuditLog.query.filter_by(action="central_link_removido").first()
    assert entrada is not None
    assert entrada.details["id_auvo"] == 111


def test_remover_link_pendente_levanta_erro(app):
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "AUTO MECANICA"}], simulacao=True, user_id=None)
    item = lote.itens[0]
    assert item.status == "pendente"

    try:
        svc.remover_link(item)
        assert False, "deveria ter levantado CentralClienteLinkNaoRemovivelError"
    except svc.CentralClienteLinkNaoRemovivelError:
        pass
    assert item.status == "pendente"


def test_remover_link_ja_removido_levanta_erro(app):
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "AUTO MECANICA"}], simulacao=True, user_id=None)
    svc.executar_lote(lote, credentials=None, config=app.config, sleep_fn=_sem_pausa)
    item = lote.itens[0]
    svc.remover_link(item)
    db.session.commit()

    try:
        svc.remover_link(item)
        assert False, "deveria ter levantado CentralClienteLinkNaoRemovivelError"
    except svc.CentralClienteLinkNaoRemovivelError:
        pass


def test_montar_lote_permite_novo_candidato_apos_remover(app):
    _depara("95", 111, status="OK", score=0.9, nome="AUTO MECANICA")
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "AUTO MECANICA"}], simulacao=False, user_id=None)
    svc.executar_lote(
        lote,
        credentials=PainelCredentials(cookie="x", auvo_user_request="1"),
        config=app.config,
        client=FakePainelClient(),
        sleep_fn=_sem_pausa,
    )
    assert svc.montar_lote(score_minimo=0.70) == []

    svc.remover_link(lote.itens[0])
    db.session.commit()

    candidatos = svc.montar_lote(score_minimo=0.70)
    assert [c["id_auvo"] for c in candidatos] == [111]


def test_buscar_clientes_nao_mostra_link_removido(app):
    _depara("95", 111, nome="AUTO MECANICA")
    lote = svc.criar_lote([{"id_auvo": 111, "nome": "AUTO MECANICA"}], simulacao=True, user_id=None)
    svc.executar_lote(lote, credentials=None, config=app.config, sleep_fn=_sem_pausa)
    svc.remover_link(lote.itens[0])
    db.session.commit()

    resultados = svc.buscar_clientes("111")
    assert resultados[0]["link_existente"] is None
