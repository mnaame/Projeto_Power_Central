from app.extensions import db
from app.models.audit import AuditLog
from app.models.auvo import AuvoDepara
from app.models.central_cliente import CentralClienteLink, CentralClienteLote


def _depara(conta, id_auvo, *, status="OK", score=0.9, nome="CLIENTE X"):
    linha = AuvoDepara(conta_power=conta, nome_power=nome, id_auvo=id_auvo, status=status, score=score)
    db.session.add(linha)
    db.session.commit()
    return linha


# ---------- permissões ----------


def test_index_requer_login(client):
    resposta = client.get("/central-cliente", follow_redirects=False)
    assert resposta.status_code == 302
    assert "/auth/login" in resposta.headers["Location"]


def test_operador_nao_acessa_index(operador_client):
    assert operador_client.get("/central-cliente").status_code == 403


def test_admin_acessa_index(admin_client):
    resposta = admin_client.get("/central-cliente")
    assert resposta.status_code == 200
    assert "simulação".encode("utf-8") in resposta.data


# ---------- buscar cliente ----------


def test_buscar_sem_termo_nao_mostra_resultados(admin_client):
    resposta = admin_client.get("/central-cliente")
    assert resposta.status_code == 200
    assert "Nenhum cliente encontrado".encode("utf-8") not in resposta.data


def test_buscar_por_nome_encontra_cliente(app, admin_client):
    _depara("95", 111, nome="AUTO MECANICA CENTRO")
    resposta = admin_client.get("/central-cliente?q=auto+mecanica")
    assert resposta.status_code == 200
    assert b"AUTO MECANICA CENTRO" in resposta.data


def test_buscar_sem_resultado_mostra_aviso(admin_client):
    resposta = admin_client.get("/central-cliente?q=ninguem-com-esse-nome")
    assert resposta.status_code == 200
    assert "Nenhum cliente encontrado".encode("utf-8") in resposta.data


def test_buscar_mostra_ja_tem_link_em_vez_de_sumir(app, admin_client):
    _depara("95", 111, nome="AUTO MECANICA")
    admin_client.post(
        "/central-cliente/executar",
        data={
            "total_linhas": "1",
            "selecionar": "0",
            "id_auvo_0": "111",
            "nome_0": "AUTO MECANICA",
        },
    )
    resposta = admin_client.get("/central-cliente?q=111")
    assert resposta.status_code == 200
    assert "já tem link".encode("utf-8") in resposta.data
    assert b"Ver lote" in resposta.data


def test_operador_nao_acessa_configuracao(operador_client):
    assert operador_client.get("/central-cliente/configuracao").status_code == 403


def test_admin_acessa_configuracao(admin_client):
    assert admin_client.get("/central-cliente/configuracao").status_code == 200


def test_operador_nao_executa(operador_client):
    resposta = operador_client.post(
        "/central-cliente/executar",
        data={"total_linhas": "0"},
    )
    assert resposta.status_code == 403


# ---------- preparar (pré-visualização) ----------


def test_preparar_sem_candidatos_mostra_estado_vazio(admin_client):
    resposta = admin_client.post(
        "/central-cliente/preparar", data={"score_minimo": "", "ids_extra": ""}
    )
    assert resposta.status_code == 200
    assert "Nenhum cliente elegível".encode("utf-8") in resposta.data


def test_preparar_mostra_candidato_elegivel(app, admin_client):
    _depara("95", 111, status="OK", score=0.9, nome="CLIENTE ELEGIVEL")
    resposta = admin_client.post(
        "/central-cliente/preparar", data={"score_minimo": "0.70", "ids_extra": ""}
    )
    assert resposta.status_code == 200
    assert b"CLIENTE ELEGIVEL" in resposta.data
    assert b"111" in resposta.data


def test_preparar_com_ids_extra_inclui_manual(app, admin_client):
    _depara("95", 111, status="REVISAR", score=0.4, nome="CLIENTE MANUAL")
    resposta = admin_client.post(
        "/central-cliente/preparar", data={"score_minimo": "0.70", "ids_extra": "111"}
    )
    assert resposta.status_code == 200
    assert b"CLIENTE MANUAL" in resposta.data
    assert "marcado na mão".encode("utf-8") in resposta.data


def test_preparar_com_caixas_marcadas_inclui_sem_digitar_id(app, admin_client):
    """A lista "Clientes sem link" manda os ids nas caixas — quem nunca
    gerou link não tem o id_auvo à mão pra digitar no campo de texto."""
    _depara("95", 111, status="REVISAR", score=0.4, nome="CLIENTE MARCADO")
    resposta = admin_client.post(
        "/central-cliente/preparar",
        data={"score_minimo": "0.70", "ids_extra": "", "extra": "111"},
    )
    assert resposta.status_code == 200
    assert b"CLIENTE MARCADO" in resposta.data
    assert "marcado na mão".encode("utf-8") in resposta.data


def test_preparar_junta_caixas_e_campo_de_texto_sem_duplicar(app, admin_client):
    _depara("95", 111, status="REVISAR", score=0.4, nome="CLIENTE UM")
    _depara("96", 222, status="REVISAR", score=0.4, nome="CLIENTE DOIS")
    resposta = admin_client.post(
        "/central-cliente/preparar",
        data={"score_minimo": "0.70", "ids_extra": "111", "extra": ["111", "222"]},
    )
    assert resposta.status_code == 200
    assert b"CLIENTE UM" in resposta.data
    assert b"CLIENTE DOIS" in resposta.data
    evento = AuditLog.query.filter_by(action="central_lote_preparado").one()
    assert evento.details["ids_extra"] == [111, 222]  # sem repetir o 111


# ---------- lista de quem está sem link ----------


def test_index_lista_quem_esta_sem_link_com_motivo(app, admin_client):
    _depara("95", 111, status="REVISAR", score=0.95, nome="PRECISA CONFIRMAR")
    resposta = admin_client.get("/central-cliente")
    assert resposta.status_code == 200
    assert b"Clientes sem link" in resposta.data
    assert b"PRECISA CONFIRMAR" in resposta.data


def test_index_sem_link_nao_mostra_quem_ja_tem_link(app, admin_client):
    lote = CentralClienteLote(simulacao=False, status="success", total_itens=1)
    db.session.add(lote)
    db.session.flush()
    db.session.add(CentralClienteLink(lote_id=lote.id, id_auvo=111, nome="X", status="criado"))
    db.session.commit()
    _depara("95", 111, status="OK", score=0.9, nome="JA TEM LINK")

    resposta = admin_client.get("/central-cliente")
    assert resposta.status_code == 200
    assert b"JA TEM LINK" not in resposta.data
    assert "Todas as contas do de-para já têm link".encode("utf-8") in resposta.data


# ---------- executar ----------


def test_executar_simulacao_cria_lote_e_marca_criado(app, admin_client):
    resposta = admin_client.post(
        "/central-cliente/executar",
        data={
            "total_linhas": "1",
            "selecionar": "0",
            "id_auvo_0": "111",
            "nome_0": "CLIENTE X",
        },
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    lote = CentralClienteLote.query.order_by(CentralClienteLote.id.desc()).first()
    assert lote is not None
    assert lote.simulacao is True
    assert lote.status == "success"
    assert lote.total_sucesso == 1
    item = lote.itens[0]
    assert item.status == "criado"
    assert item.link_url


def test_executar_sem_selecao_avisa(admin_client):
    resposta = admin_client.post(
        "/central-cliente/executar", data={"total_linhas": "0"}, follow_redirects=True
    )
    assert resposta.status_code == 200
    assert "Selecione ao menos um cliente".encode("utf-8") in resposta.data
    assert CentralClienteLote.query.count() == 0


def test_executar_producao_sem_confirmar_nao_cria_lote(app, admin_client):
    from app.services import settings_service

    settings_service.set("central_simulacao", "false")
    db.session.commit()

    resposta = admin_client.post(
        "/central-cliente/executar",
        data={
            "total_linhas": "1",
            "selecionar": "0",
            "id_auvo_0": "111",
            "nome_0": "CLIENTE X",
        },
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    assert "confirma".encode("utf-8") in resposta.data.lower() or "confirmação".encode("utf-8") in resposta.data
    assert CentralClienteLote.query.count() == 0


def test_executar_producao_sem_cookie_nao_cria_lote(app, admin_client):
    from app.services import settings_service

    settings_service.set("central_simulacao", "false")
    db.session.commit()

    resposta = admin_client.post(
        "/central-cliente/executar",
        data={
            "total_linhas": "1",
            "selecionar": "0",
            "id_auvo_0": "111",
            "nome_0": "CLIENTE X",
            "confirmar": "sim",
        },
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    assert CentralClienteLote.query.count() == 0


def test_executar_producao_com_cookie_cria_contato(app, admin_client, monkeypatch):
    from app.integrations.auvo_painel_client import CentralClientePainelClient
    from app.services import central_cliente_service, settings_service

    settings_service.set("central_simulacao", "false")
    db.session.commit()

    def _fake_criar_contato_link(self, *, codigo_cliente, **kwargs):
        return 999

    monkeypatch.setattr(
        CentralClientePainelClient, "criar_contato_link", _fake_criar_contato_link
    )

    resposta = admin_client.post(
        "/central-cliente/executar",
        data={
            "total_linhas": "1",
            "selecionar": "0",
            "id_auvo_0": "111",
            "nome_0": "CLIENTE X",
            "confirmar": "sim",
            "cookie": "sessao=abc123",
            "auvo_user_request": "42",
        },
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    lote = CentralClienteLote.query.order_by(CentralClienteLote.id.desc()).first()
    assert lote is not None
    assert lote.simulacao is False
    assert lote.status == "success"
    assert lote.itens[0].contato_codigo == 999

    entrada = AuditLog.query.filter_by(action="central_link_criado").first()
    assert entrada is not None
    assert "abc123" not in str(entrada.details)


def test_lote_detalhe_inexistente_404(admin_client):
    assert admin_client.get("/central-cliente/lote/999999").status_code == 404


def test_exportar_gera_xlsx(app, admin_client):
    admin_client.post(
        "/central-cliente/executar",
        data={
            "total_linhas": "1",
            "selecionar": "0",
            "id_auvo_0": "111",
            "nome_0": "CLIENTE X",
        },
    )
    lote = CentralClienteLote.query.order_by(CentralClienteLote.id.desc()).first()
    resposta = admin_client.get(f"/central-cliente/exportar/{lote.id}")
    assert resposta.status_code == 200
    assert resposta.headers["Content-Type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# ---------- whatsapp ----------


def test_whatsapp_com_telefone_audita_e_redireciona(app, admin_client, monkeypatch):
    from app.services import central_cliente_service

    monkeypatch.setattr(central_cliente_service.auvo_service, "criar_cliente", lambda config: object())
    monkeypatch.setattr(
        central_cliente_service, "_mapa_telefones", lambda client: {111: ["31999998888"]}
    )

    admin_client.post(
        "/central-cliente/executar",
        data={
            "total_linhas": "1",
            "selecionar": "0",
            "id_auvo_0": "111",
            "nome_0": "CLIENTE X",
        },
    )
    lote = CentralClienteLote.query.order_by(CentralClienteLote.id.desc()).first()
    item = lote.itens[0]
    assert item.telefones == ["5531999998888"]

    resposta = admin_client.get(
        f"/central-cliente/lote/{lote.id}/item/{item.id}/whatsapp", follow_redirects=False
    )
    assert resposta.status_code == 302
    assert resposta.headers["Location"].startswith("https://wa.me/5531999998888?text=")

    entrada = AuditLog.query.filter_by(action="central_whatsapp_aberto").first()
    assert entrada is not None
    assert entrada.details["id_auvo"] == 111
    assert entrada.details["telefone"] == "5531999998888"


def test_whatsapp_com_dois_telefones_escolhe_pela_querystring(app, admin_client, monkeypatch):
    from app.services import central_cliente_service

    monkeypatch.setattr(central_cliente_service.auvo_service, "criar_cliente", lambda config: object())
    monkeypatch.setattr(
        central_cliente_service,
        "_mapa_telefones",
        lambda client: {111: ["31995222809", "31996837126"]},
    )

    admin_client.post(
        "/central-cliente/executar",
        data={
            "total_linhas": "1",
            "selecionar": "0",
            "id_auvo_0": "111",
            "nome_0": "CLIENTE X",
        },
    )
    lote = CentralClienteLote.query.order_by(CentralClienteLote.id.desc()).first()
    item = lote.itens[0]
    assert item.telefones == ["5531995222809", "5531996837126"]

    resposta = admin_client.get(
        f"/central-cliente/lote/{lote.id}/item/{item.id}/whatsapp?telefone=5531996837126",
        follow_redirects=False,
    )
    assert resposta.status_code == 302
    assert resposta.headers["Location"].startswith("https://wa.me/5531996837126?text=")


def test_whatsapp_telefone_arbitrario_na_querystring_404(app, admin_client, monkeypatch):
    from app.services import central_cliente_service

    monkeypatch.setattr(central_cliente_service.auvo_service, "criar_cliente", lambda config: object())
    monkeypatch.setattr(
        central_cliente_service, "_mapa_telefones", lambda client: {111: ["31999998888"]}
    )

    admin_client.post(
        "/central-cliente/executar",
        data={
            "total_linhas": "1",
            "selecionar": "0",
            "id_auvo_0": "111",
            "nome_0": "CLIENTE X",
        },
    )
    lote = CentralClienteLote.query.order_by(CentralClienteLote.id.desc()).first()
    item = lote.itens[0]

    resposta = admin_client.get(
        f"/central-cliente/lote/{lote.id}/item/{item.id}/whatsapp?telefone=5511900000000"
    )
    assert resposta.status_code == 404


def test_whatsapp_sem_telefone_404(app, admin_client):
    admin_client.post(
        "/central-cliente/executar",
        data={
            "total_linhas": "1",
            "selecionar": "0",
            "id_auvo_0": "111",
            "nome_0": "CLIENTE X",
        },
    )
    lote = CentralClienteLote.query.order_by(CentralClienteLote.id.desc()).first()
    item = lote.itens[0]
    assert item.telefones is None

    resposta = admin_client.get(f"/central-cliente/lote/{lote.id}/item/{item.id}/whatsapp")
    assert resposta.status_code == 404


def test_whatsapp_item_de_outro_lote_404(app, admin_client):
    for i in range(2):
        admin_client.post(
            "/central-cliente/executar",
            data={
                "total_linhas": "1",
                "selecionar": "0",
                "id_auvo_0": str(111 + i),
                "nome_0": "CLIENTE X",
            },
        )
    lotes = CentralClienteLote.query.order_by(CentralClienteLote.id).all()
    primeiro_item = lotes[0].itens[0]
    segundo_lote = lotes[1]

    resposta = admin_client.get(
        f"/central-cliente/lote/{segundo_lote.id}/item/{primeiro_item.id}/whatsapp"
    )
    assert resposta.status_code == 404


def test_operador_nao_acessa_whatsapp(operador_client):
    assert operador_client.get("/central-cliente/lote/1/item/1/whatsapp").status_code == 403


# ---------- remover ----------


def test_remover_marca_removido_e_libera_para_novo_lote(app, admin_client):
    _depara("95", 111, nome="AUTO MECANICA")
    admin_client.post(
        "/central-cliente/executar",
        data={
            "total_linhas": "1",
            "selecionar": "0",
            "id_auvo_0": "111",
            "nome_0": "AUTO MECANICA",
        },
    )
    lote = CentralClienteLote.query.order_by(CentralClienteLote.id.desc()).first()
    item = lote.itens[0]
    assert item.status == "criado"

    resposta = admin_client.post(
        f"/central-cliente/lote/{lote.id}/item/{item.id}/remover", follow_redirects=True
    )
    assert resposta.status_code == 200
    assert db.session.get(CentralClienteLink, item.id).status == "removido"

    entrada = AuditLog.query.filter_by(action="central_link_removido").first()
    assert entrada is not None

    # volta a aparecer numa nova pré-visualização
    resposta_preparar = admin_client.post(
        "/central-cliente/preparar", data={"score_minimo": "0.70", "ids_extra": ""}
    )
    assert b"AUTO MECANICA" in resposta_preparar.data


def test_remover_item_pendente_nao_remove(app, admin_client):
    lote = CentralClienteLote(simulacao=True, status="running", total_itens=1)
    db.session.add(lote)
    db.session.flush()
    item = CentralClienteLink(lote_id=lote.id, id_auvo=111, nome="X", status="pendente")
    db.session.add(item)
    db.session.commit()

    resposta = admin_client.post(
        f"/central-cliente/lote/{lote.id}/item/{item.id}/remover", follow_redirects=True
    )
    assert resposta.status_code == 200
    assert db.session.get(CentralClienteLink, item.id).status == "pendente"


def test_remover_item_de_outro_lote_404(app, admin_client):
    for i in range(2):
        admin_client.post(
            "/central-cliente/executar",
            data={
                "total_linhas": "1",
                "selecionar": "0",
                "id_auvo_0": str(111 + i),
                "nome_0": "CLIENTE X",
            },
        )
    lotes = CentralClienteLote.query.order_by(CentralClienteLote.id).all()
    primeiro_item = lotes[0].itens[0]
    segundo_lote = lotes[1]

    resposta = admin_client.post(
        f"/central-cliente/lote/{segundo_lote.id}/item/{primeiro_item.id}/remover"
    )
    assert resposta.status_code == 404


def test_operador_nao_remove(operador_client):
    assert operador_client.post("/central-cliente/lote/1/item/1/remover").status_code == 403


# ---------- configuração ----------


def test_salvar_configuracao(app, admin_client):
    resposta = admin_client.post(
        "/central-cliente/configuracao/salvar",
        data={
            "score_minimo": "0.85",
            "auvo_user_request": "77",
            "cargo_padrao": "Contato Cliente",
            "pausa_segundos": "2",
            "menu_solicitacoes": "y",
            "menu_os": "y",
            "whatsapp_template": "Oi {nome}, acesse: {link}",
        },
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    from app.services import settings_service

    assert settings_service.get_central_score_minimo() == 0.85
    assert settings_service.get_central_auvo_user_request() == "77"
    assert settings_service.get_central_cargo_padrao() == "Contato Cliente"
    assert settings_service.get_central_pausa_segundos() == 2.0
    assert settings_service.central_menu_solicitacoes() is True
    assert settings_service.central_menu_orcamento() is False


def test_salvar_configuracao_sem_mensagem_whatsapp_nao_salva(app, admin_client):
    """whatsapp_template é obrigatório — sem ele a validação falha e nada
    (nem os outros campos do form) é salvo, form volta com erro."""
    from app.services import settings_service

    resposta = admin_client.post(
        "/central-cliente/configuracao/salvar",
        data={
            "score_minimo": "0.85",
            "cargo_padrao": "Contato Cliente",
            "pausa_segundos": "2",
        },
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    assert settings_service.get_central_score_minimo() != 0.85


def test_salvar_configuracao_whatsapp_ddi_e_template(app, admin_client):
    from app.services import settings_service

    admin_client.post(
        "/central-cliente/configuracao/salvar",
        data={
            "score_minimo": "0.85",
            "cargo_padrao": "Contato Cliente",
            "pausa_segundos": "2",
            "whatsapp_ddi": "351",
            "whatsapp_template": "Ola {nome}, seu acesso: {link}",
        },
        follow_redirects=True,
    )
    assert settings_service.get_central_whatsapp_ddi() == "351"
    assert settings_service.get_central_whatsapp_template() == "Ola {nome}, seu acesso: {link}"


def test_salvar_configuracao_whatsapp_ddi_vazio_usa_padrao(app, admin_client):
    from app.services import settings_service

    admin_client.post(
        "/central-cliente/configuracao/salvar",
        data={
            "score_minimo": "0.85",
            "cargo_padrao": "Contato Cliente",
            "pausa_segundos": "2",
            "whatsapp_ddi": "",
            "whatsapp_template": "Oi {nome}: {link}",
        },
        follow_redirects=True,
    )
    assert settings_service.get_central_whatsapp_ddi() == "55"


def test_alternar_modo_producao_exige_confirmacao(admin_client):
    resposta = admin_client.post(
        "/central-cliente/modo", data={"modo": "producao"}, follow_redirects=True
    )
    assert resposta.status_code == 200
    from app.services import settings_service

    assert settings_service.central_simulacao() is True


def test_alternar_modo_producao_com_confirmacao(admin_client):
    resposta = admin_client.post(
        "/central-cliente/modo",
        data={"modo": "producao", "confirmar": "sim"},
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    from app.services import settings_service

    assert settings_service.central_simulacao() is False
