import pytest
from flask_login import login_required

from app import create_app
from app.extensions import db as _db
from app.models.user import User
from app.security import hash_password
from app.web.auth.decorators import roles_required


def _registrar_rota_admin_teste(application) -> None:
    """Rota só para exercitar `roles_required` nos testes de RBAC — o
    Phase 4 é quem vai adicionar rotas de admin reais. Precisa ser
    registrada antes da primeira requisição (trava do Flask)."""

    @application.route("/_teste/admin-only", endpoint="rota_admin_teste")
    @login_required
    @roles_required("admin")
    def _admin_only():
        return "ok-admin"


@pytest.fixture()
def app():
    application = create_app("testing")
    _registrar_rota_admin_teste(application)
    with application.app_context():
        _db.create_all()
        yield application
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def _criar_usuario(username: str, role: str) -> User:
    usuario = User(
        username=username,
        password_hash=hash_password("senha-forte-123"),
        role=role,
        active=True,
    )
    _db.session.add(usuario)
    _db.session.commit()
    return usuario


@pytest.fixture()
def admin_user(app):
    return _criar_usuario("admin.teste", "admin")


@pytest.fixture()
def operador_user(app):
    return _criar_usuario("operador.teste", "operador")


def _login(client, username: str) -> None:
    resposta = client.post(
        "/auth/login",
        data={"username": username, "password": "senha-forte-123"},
        follow_redirects=True,
    )
    assert resposta.status_code == 200


@pytest.fixture()
def admin_client(client, admin_user):
    _login(client, admin_user.username)
    return client


@pytest.fixture()
def operador_client(client, operador_user):
    _login(client, operador_user.username)
    return client
