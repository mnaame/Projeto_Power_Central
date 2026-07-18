from app.models.audit import AuditLog


def test_admin_acessa_rota_restrita(admin_client):
    resposta = admin_client.get("/_teste/admin-only")
    assert resposta.status_code == 200
    assert resposta.data == b"ok-admin"


def test_operador_recebe_403_e_fica_na_auditoria(app, operador_client):
    resposta = operador_client.get("/_teste/admin-only")
    assert resposta.status_code == 403

    evento = AuditLog.query.filter_by(action="unauthorized_access_attempt").first()
    assert evento is not None
    assert evento.result == "failure"
    assert evento.details["path"] == "/_teste/admin-only"
    assert evento.details["required_roles"] == ["admin"]


def test_anonimo_e_redirecionado_para_login(client):
    resposta = client.get("/_teste/admin-only", follow_redirects=False)
    assert resposta.status_code == 302
    assert "/auth/login" in resposta.headers["Location"]
