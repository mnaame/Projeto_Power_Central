def test_create_app_testing_config(app):
    assert app.config["TESTING"] is True


def test_health_endpoint_reports_db_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "db_ok": True}
