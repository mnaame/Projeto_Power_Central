from app.extensions import db
from app.models.audit import AuditLog
from app.models.user import User
from app.security import hash_password


def test_login_page_renders(client):
    resposta = client.get("/auth/login")
    assert resposta.status_code == 200
    assert "Entrar".encode() in resposta.data


def test_login_com_credenciais_corretas_redireciona_ao_painel(client, operador_user):
    resposta = client.post(
        "/auth/login",
        data={"username": operador_user.username, "password": "senha-forte-123"},
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    assert b"dashboard-content" in resposta.data


def test_login_com_senha_errada_mostra_erro_e_nao_autentica(client, operador_user):
    resposta = client.post(
        "/auth/login",
        data={"username": operador_user.username, "password": "errada"},
    )
    assert resposta.status_code == 200
    assert "inválidos".encode() in resposta.data


def test_login_registra_auditoria_sucesso_e_falha(app, client, operador_user):
    # a tentativa com senha errada precisa vir primeiro: depois de autenticado,
    # o mesmo cliente é redirecionado direto pelo /login sem reavaliar credenciais.
    client.post(
        "/auth/login",
        data={"username": operador_user.username, "password": "errada"},
    )
    client.post(
        "/auth/login",
        data={"username": operador_user.username, "password": "senha-forte-123"},
    )

    eventos = AuditLog.query.order_by(AuditLog.id).all()
    assert [e.action for e in eventos] == ["login", "login"]
    assert [e.result for e in eventos] == ["failure", "success"]


def test_usuario_inativo_nao_consegue_logar(app, client):
    usuario = User(
        username="inativo",
        password_hash=hash_password("senha-forte-123"),
        role="operador",
        active=False,
    )
    db.session.add(usuario)
    db.session.commit()

    resposta = client.post(
        "/auth/login", data={"username": "inativo", "password": "senha-forte-123"}
    )
    assert resposta.status_code == 200
    assert "inválidos".encode() in resposta.data


def test_logout_encerra_sessao(operador_client):
    resposta = operador_client.post("/auth/logout", follow_redirects=True)
    assert resposta.status_code == 200

    resposta_painel = operador_client.get("/", follow_redirects=False)
    assert resposta_painel.status_code == 302
    assert "/auth/login" in resposta_painel.headers["Location"]


def test_painel_requer_login(client):
    resposta = client.get("/", follow_redirects=False)
    assert resposta.status_code == 302
    assert "/auth/login" in resposta.headers["Location"]
