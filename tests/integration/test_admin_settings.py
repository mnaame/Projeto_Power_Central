from app.services import settings_service


def test_operador_nao_acessa_configuracoes(operador_client):
    resposta = operador_client.get("/admin/configuracoes")
    assert resposta.status_code == 403


def test_admin_ve_configuracoes(admin_client):
    resposta = admin_client.get("/admin/configuracoes")
    assert resposta.status_code == 200


def test_admin_salva_configuracoes(app, admin_client):
    resposta = admin_client.post(
        "/admin/configuracoes",
        data={
            "window_hours": "5",
            "confirming_codes": "TST, CLO, OPN, PAN",
            "collector_interval_minutes": "10",
            "watchdog_threshold_minutes": "20",
            "manual_cooldown_seconds": "30",
            "retention_days": "60",
            "show_false_positives_in_panel": "y",
        },
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    assert settings_service.get_window_hours() == 5.0
    assert settings_service.get_confirming_codes() == ("CLO", "OPN", "PAN", "TST")
    assert settings_service.get_collector_interval_minutes() == 10
    assert settings_service.get_watchdog_threshold_minutes() == 20.0
    assert settings_service.get_manual_cooldown_seconds() == 30
    assert settings_service.get_retention_days() == 60
    assert settings_service.show_false_positives_in_panel() is True


def test_admin_desliga_falsos_positivos_quando_checkbox_ausente(app, admin_client):
    admin_client.post(
        "/admin/configuracoes",
        data={
            "window_hours": "3",
            "confirming_codes": "TST",
            "collector_interval_minutes": "5",
            "watchdog_threshold_minutes": "15",
            "manual_cooldown_seconds": "60",
            "retention_days": "90",
            # show_false_positives_in_panel ausente = desmarcado
        },
        follow_redirects=True,
    )
    assert settings_service.show_false_positives_in_panel() is False


def test_admin_configuracoes_invalidas_nao_salvam(app, admin_client):
    resposta = admin_client.post(
        "/admin/configuracoes",
        data={
            "window_hours": "999",  # acima do máximo permitido
            "confirming_codes": "TST",
            "collector_interval_minutes": "5",
            "watchdog_threshold_minutes": "15",
            "manual_cooldown_seconds": "60",
            "retention_days": "90",
        },
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    assert settings_service.get_window_hours() == 3.0  # padrão, não mudou


def test_admin_salva_telegram_e_status_muda(admin_client):
    resposta = admin_client.post(
        "/admin/configuracoes/telegram",
        data={"bot_token": "123:ABC", "chat_id": "-100999"},
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    assert "Configurado".encode() in resposta.data


def test_testar_telegram_sem_configuracao_avisa(admin_client):
    resposta = admin_client.post("/admin/configuracoes/telegram/testar", follow_redirects=True)
    assert resposta.status_code == 200
    assert "não está configurado".encode() in resposta.data
