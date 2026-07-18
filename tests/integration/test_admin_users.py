from app.extensions import db
from app.models.user import User
from app.security import verify_password


def test_operador_nao_acessa_gestao_de_usuarios(operador_client):
    resposta = operador_client.get("/admin/usuarios")
    assert resposta.status_code == 403


def test_admin_acessa_gestao_de_usuarios(admin_client):
    resposta = admin_client.get("/admin/usuarios")
    assert resposta.status_code == 200


def test_admin_cria_usuario(app, admin_client):
    resposta = admin_client.post(
        "/admin/usuarios",
        data={"username": "novo.usuario", "password": "senha-forte-123", "role": "operador"},
        follow_redirects=True,
    )
    assert resposta.status_code == 200

    criado = User.query.filter_by(username="novo.usuario").first()
    assert criado is not None
    assert criado.role == "operador"
    assert verify_password(criado.password_hash, "senha-forte-123")


def test_admin_nao_cria_usuario_duplicado(app, admin_client, operador_user):
    resposta = admin_client.post(
        "/admin/usuarios",
        data={
            "username": operador_user.username,
            "password": "senha-forte-123",
            "role": "operador",
        },
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    assert User.query.filter_by(username=operador_user.username).count() == 1


def test_admin_desativa_usuario(app, admin_client, operador_user):
    resposta = admin_client.post(
        f"/admin/usuarios/{operador_user.id}/alternar-status", follow_redirects=True
    )
    assert resposta.status_code == 200
    assert db.session.get(User, operador_user.id).active is False


def test_admin_nao_desativa_a_si_mesmo(app, admin_client, admin_user):
    admin_client.post(f"/admin/usuarios/{admin_user.id}/alternar-status", follow_redirects=True)
    assert db.session.get(User, admin_user.id).active is True


def test_admin_troca_senha_de_usuario(app, admin_client, operador_user):
    resposta = admin_client.post(
        f"/admin/usuarios/{operador_user.id}/senha",
        data={"password": "nova-senha-123"},
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    atualizado = db.session.get(User, operador_user.id)
    assert verify_password(atualizado.password_hash, "nova-senha-123")


def test_operador_nao_consegue_criar_usuario(operador_client):
    resposta = operador_client.post(
        "/admin/usuarios",
        data={"username": "hacker", "password": "senha-forte-123", "role": "admin"},
    )
    assert resposta.status_code == 403
    assert User.query.filter_by(username="hacker").first() is None
