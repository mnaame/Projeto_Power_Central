def test_operador_nao_acessa_auditoria(operador_client):
    resposta = operador_client.get("/admin/auditoria")
    assert resposta.status_code == 403


def test_admin_ve_auditoria_apos_login(admin_client):
    resposta = admin_client.get("/admin/auditoria")
    assert resposta.status_code == 200
    assert b"login" in resposta.data


def test_filtro_por_resultado(app, admin_client, operador_user):
    outro_client = app.test_client()
    outro_client.post(
        "/auth/login", data={"username": operador_user.username, "password": "senha-errada"}
    )

    resposta = admin_client.get("/admin/auditoria?resultado=failure")
    assert resposta.status_code == 200
    assert "Falha".encode() in resposta.data


def test_filtro_por_usuario_sem_resultado_mostra_vazio(admin_client):
    resposta = admin_client.get("/admin/auditoria?usuario=inexistente-xyz")
    assert resposta.status_code == 200
    assert "Nenhum evento".encode() in resposta.data
