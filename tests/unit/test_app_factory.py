def test_create_app_testing_config(app):
    assert app.config["TESTING"] is True


def test_health_endpoint_reports_db_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["db_ok"] is True
    assert payload["last_cycle_at"] is None
    assert payload["watchdog_alert_active"] is False
