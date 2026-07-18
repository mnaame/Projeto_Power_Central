from cryptography.fernet import Fernet

from app.extensions import db
from app.models.settings import Setting
from app.services import settings_service


def test_get_retorna_padrao_quando_nao_configurado(app):
    assert settings_service.get_window_hours() == 3.0
    assert settings_service.get_confirming_codes() == ("TST", "CLO", "OPN")
    assert settings_service.get_collector_interval_minutes() == 5
    assert settings_service.get_watchdog_threshold_minutes() == 15.0


def test_set_e_get_roundtrip(app):
    settings_service.set("window_hours", "5")
    db.session.commit()

    assert settings_service.get_window_hours() == 5.0


def test_telegram_credentials_roundtrip_cifrado(app):
    chave = Fernet.generate_key().decode()

    settings_service.set_telegram_credentials("token-123", "-100200300", encryption_key=chave)
    db.session.commit()

    bruto = db.session.get(Setting, "telegram_bot_token").value
    assert "token-123" not in bruto

    token, chat_id = settings_service.get_telegram_credentials(encryption_key=chave)
    assert token == "token-123"
    assert chat_id == "-100200300"


def test_get_telegram_credentials_none_quando_nao_configurado(app):
    chave = Fernet.generate_key().decode()
    assert settings_service.get_telegram_credentials(encryption_key=chave) is None


def test_get_telegram_credentials_none_com_chave_errada(app):
    chave_certa = Fernet.generate_key().decode()
    chave_errada = Fernet.generate_key().decode()

    settings_service.set_telegram_credentials(
        "token-123", "-100200300", encryption_key=chave_certa
    )
    db.session.commit()

    assert settings_service.get_telegram_credentials(encryption_key=chave_errada) is None
