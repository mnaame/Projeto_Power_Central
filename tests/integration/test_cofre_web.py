from app.extensions import db
from app.models.audit import AuditLog
from app.models.cofre import Segredo
from app.services import cofre_service


def _criar_segredo(
    app, *, titulo="DVR Loja Centro", nivel="equipe", senha="senha-atual-123", notas=None
):
    segredo = cofre_service.criar(
        titulo=titulo,
        categoria="camera",
        login="admin",
        senha=senha,
        url="http://192.168.0.10",
        notas=notas,
        nivel=nivel,
        user_id=None,
        config=app.config,
    )
    db.session.commit()
    return segredo.id


# ---------- permissões ----------


def test_index_requer_login(client):
    resposta = client.get("/cofre", follow_redirects=False)
    assert resposta.status_code == 302
    assert "/auth/login" in resposta.headers["Location"]


def test_operador_acessa_index(operador_client):
    assert operador_client.get("/cofre").status_code == 200


def test_operador_nao_ve_item_restrito_na_lista(app, operador_client):
    _criar_segredo(app, titulo="Painel Restrito", nivel="restrito")
    _criar_segredo(app, titulo="Roteador Loja", nivel="equipe")
    resposta = operador_client.get("/cofre")
    assert b"Roteador Loja" in resposta.data
    assert b"Painel Restrito" not in resposta.data


def test_admin_ve_itens_restrito_e_equipe(app, admin_client):
    _criar_segredo(app, titulo="Painel Restrito", nivel="restrito")
    resposta = admin_client.get("/cofre")
    assert b"Painel Restrito" in resposta.data


def test_operador_acessando_restrito_por_id_direto_403_e_audita(app, operador_client):
    segredo_id = _criar_segredo(app, titulo="Painel Restrito", nivel="restrito")
    resposta = operador_client.get(f"/cofre/{segredo_id}/editar")
    assert resposta.status_code == 403

    entrada = AuditLog.query.filter_by(action="cofre_acesso_negado").first()
    assert entrada is not None
    assert entrada.result == "failure"


def test_operador_nao_acessa_configuracao(operador_client):
    assert operador_client.get("/cofre/configuracao").status_code == 403


def test_admin_acessa_configuracao(admin_client):
    assert admin_client.get("/cofre/configuracao").status_code == 200


def test_configuracao_mostra_status_da_chave(admin_client):
    resposta = admin_client.get("/cofre/configuracao")
    assert "Configurada".encode("utf-8") in resposta.data


# ---------- CRUD ----------


def test_criar_segredo(app, operador_client):
    resposta = operador_client.post(
        "/cofre/novo",
        data={
            "titulo": "E-mail Suporte",
            "categoria": "email",
            "login": "suporte@empresa.com",
            "senha": "uma-senha-bem-forte-123!",
            "url": "",
            "notas": "",
            "nivel": "equipe",
            "expira_em": "",
        },
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    segredo = Segredo.query.filter_by(titulo="E-mail Suporte").first()
    assert segredo is not None
    assert segredo.senha_cifrada != "uma-senha-bem-forte-123!"


def test_criar_sem_senha_mostra_aviso(operador_client):
    resposta = operador_client.post(
        "/cofre/novo",
        data={
            "titulo": "Sem senha",
            "categoria": "outro",
            "login": "",
            "senha": "",
            "url": "",
            "notas": "",
            "nivel": "equipe",
            "expira_em": "",
        },
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    assert "Informe a senha".encode("utf-8") in resposta.data


def test_operador_nao_pode_criar_restrito(operador_client):
    resposta = operador_client.post(
        "/cofre/novo",
        data={
            "titulo": "Tentativa Restrito",
            "categoria": "outro",
            "login": "",
            "senha": "uma-senha-bem-forte-123!",
            "url": "",
            "notas": "",
            "nivel": "restrito",
            "expira_em": "",
        },
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    assert "Só administradores".encode("utf-8") in resposta.data


def test_criar_sem_chave_configurada_mostra_erro_amigavel(app, operador_client, monkeypatch):
    monkeypatch.setitem(app.config, "VAULT_ENCRYPTION_KEY", None)
    resposta = operador_client.post(
        "/cofre/novo",
        data={
            "titulo": "Sem chave",
            "categoria": "outro",
            "login": "",
            "senha": "uma-senha-bem-forte-123!",
            "url": "",
            "notas": "",
            "nivel": "equipe",
            "expira_em": "",
        },
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    assert b"VAULT_ENCRYPTION_KEY" in resposta.data
    assert Segredo.query.filter_by(titulo="Sem chave").first() is None


def test_revelar_sem_chave_configurada_mostra_erro_amigavel(app, operador_client, operador_user, monkeypatch):
    segredo_id = _criar_segredo(app, senha="senha-secreta-999")
    monkeypatch.setitem(app.config, "VAULT_ENCRYPTION_KEY", None)

    resposta = operador_client.post(
        f"/cofre/{segredo_id}/revelar",
        data={"senha_reautenticacao": "senha-forte-123"},
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    assert b"senha-secreta-999" not in resposta.data
    assert b"VAULT_ENCRYPTION_KEY" in resposta.data


def test_editar_mantendo_senha_em_branco_preserva_senha_atual(app, operador_client):
    segredo_id = _criar_segredo(app, senha="senha-original-999")
    cifra_original = db.session.get(Segredo, segredo_id).senha_cifrada

    resposta = operador_client.post(
        f"/cofre/{segredo_id}/editar",
        data={
            "titulo": "DVR Loja Centro (editado)",
            "categoria": "camera",
            "login": "admin",
            "senha": "",
            "url": "http://192.168.0.10",
            "notas": "",
            "nivel": "equipe",
            "expira_em": "",
        },
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    atualizado = db.session.get(Segredo, segredo_id)
    assert atualizado.titulo == "DVR Loja Centro (editado)"
    assert atualizado.senha_cifrada == cifra_original


def test_excluir_segredo(app, operador_client):
    segredo_id = _criar_segredo(app)
    resposta = operador_client.post(f"/cofre/{segredo_id}/excluir", follow_redirects=True)
    assert resposta.status_code == 200
    assert db.session.get(Segredo, segredo_id) is None


# ---------- revelar ----------


def test_revelar_com_senha_correta_mostra_e_audita(app, operador_client, operador_user):
    segredo_id = _criar_segredo(app, senha="senha-secreta-999")

    resposta = operador_client.post(
        f"/cofre/{segredo_id}/revelar",
        data={"senha_reautenticacao": "senha-forte-123"},
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    assert b"senha-secreta-999" in resposta.data

    entrada = (
        AuditLog.query.filter_by(action="cofre_senha_revelada").order_by(AuditLog.id.desc()).first()
    )
    assert entrada is not None
    assert entrada.result == "success"
    assert "senha-secreta-999" not in str(entrada.details)


def test_revelar_com_senha_errada_nao_mostra_e_audita_falha(app, operador_client, operador_user):
    segredo_id = _criar_segredo(app, senha="senha-secreta-999")

    resposta = operador_client.post(
        f"/cofre/{segredo_id}/revelar",
        data={"senha_reautenticacao": "senha-errada"},
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    assert b"senha-secreta-999" not in resposta.data
    assert "incorreta".encode("utf-8") in resposta.data

    entrada = (
        AuditLog.query.filter_by(action="cofre_senha_revelada").order_by(AuditLog.id.desc()).first()
    )
    assert entrada is not None
    assert entrada.result == "failure"


def test_operador_nao_revela_item_restrito_por_id_direto(app, operador_client):
    segredo_id = _criar_segredo(app, titulo="Painel Restrito", nivel="restrito", senha="x123456789!")
    resposta = operador_client.post(
        f"/cofre/{segredo_id}/revelar",
        data={"senha_reautenticacao": "senha-forte-123"},
    )
    assert resposta.status_code == 403


def test_senha_nunca_aparece_na_listagem(app, operador_client):
    _criar_segredo(app, senha="segredo-nao-pode-vazar-000")
    resposta = operador_client.get("/cofre")
    assert b"segredo-nao-pode-vazar-000" not in resposta.data


# ---------- notas (bug real: sumiam ao editar) ----------


def test_editar_carrega_as_notas_no_formulario(app, operador_client):
    """`SegredoForm(obj=segredo)` preenche por NOME do atributo, e a coluna
    é `notas_cifradas` — então o campo chegava vazio à tela."""
    segredo_id = _criar_segredo(app, notas="Acesso pela porta dos fundos")

    resposta = operador_client.get(f"/cofre/{segredo_id}/editar")

    assert resposta.status_code == 200
    assert "Acesso pela porta dos fundos".encode("utf-8") in resposta.data


def test_editar_outro_campo_nao_apaga_as_notas(app, operador_client):
    """O pior sintoma: o formulário vinha vazio e salvar gravava vazio por
    cima — a nota era destruída sem ninguém pedir."""
    segredo_id = _criar_segredo(app, notas="Chave reserva com o zelador")

    operador_client.post(
        f"/cofre/{segredo_id}/editar",
        data={
            "titulo": "DVR Loja Centro (renomeado)",
            "categoria": "camera",
            "login": "admin",
            "senha": "",
            "url": "http://192.168.0.10",
            "notas": "Chave reserva com o zelador",
            "nivel": "equipe",
            "expira_em": "",
        },
        follow_redirects=True,
    )

    segredo = db.session.get(Segredo, segredo_id)
    assert segredo.titulo == "DVR Loja Centro (renomeado)"
    assert cofre_service.notas_em_claro(segredo, config=app.config) == (
        "Chave reserva com o zelador"
    )


def test_notas_salvas_na_criacao_ficam_legiveis(app, operador_client):
    operador_client.post(
        "/cofre/novo",
        data={
            "titulo": "Roteador matriz",
            "categoria": "roteador",
            "login": "admin",
            "senha": "senha-forte-123",
            "url": "",
            "notas": "IP fixo 10.0.0.1, senha do wifi na etiqueta",
            "nivel": "equipe",
            "expira_em": "",
        },
        follow_redirects=True,
    )

    segredo = Segredo.query.filter_by(titulo="Roteador matriz").one()
    assert cofre_service.notas_em_claro(segredo, config=app.config) == (
        "IP fixo 10.0.0.1, senha do wifi na etiqueta"
    )


def test_apagar_as_notas_de_proposito_continua_funcionando(app, operador_client):
    segredo_id = _criar_segredo(app, notas="nota velha")

    operador_client.post(
        f"/cofre/{segredo_id}/editar",
        data={
            "titulo": "DVR Loja Centro",
            "categoria": "camera",
            "login": "admin",
            "senha": "",
            "url": "http://192.168.0.10",
            "notas": "",
            "nivel": "equipe",
            "expira_em": "",
        },
        follow_redirects=True,
    )

    segredo = db.session.get(Segredo, segredo_id)
    assert segredo.notas_cifradas is None


def test_lista_marca_quem_tem_notas(app, operador_client):
    """Sem nenhum sinal na lista, a nota parecia não ter sido salva."""
    _criar_segredo(app, titulo="COM NOTA", notas="tem nota aqui")
    _criar_segredo(app, titulo="SEM NOTA")

    resposta = operador_client.get("/cofre")

    assert "com notas".encode("utf-8") in resposta.data
    # o conteúdo da nota NÃO é decifrado na listagem
    assert "tem nota aqui".encode("utf-8") not in resposta.data
