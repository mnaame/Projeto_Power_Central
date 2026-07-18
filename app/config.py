import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-change-me")
    ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY")

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'instance' / 'power_central.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SOFTGUARD_HOST = os.environ.get("SOFTGUARD_HOST")
    SOFTGUARD_PORT = os.environ.get("SOFTGUARD_PORT")
    SOFTGUARD_CLIENT_ID = os.environ.get("SOFTGUARD_CLIENT_ID")
    SOFTGUARD_USERNAME = os.environ.get("SOFTGUARD_USERNAME")
    SOFTGUARD_PASSWORD = os.environ.get("SOFTGUARD_PASSWORD")

    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    LOG_DIR = os.environ.get("LOG_DIR", str(BASE_DIR / "logs"))

    # Só True no processo real do serviço (ver wsgi/serviço Windows na Fase
    # 5) — nunca em comandos de CLI (migrations, seed-admin) nem em testes.
    START_SCHEDULER = os.environ.get("START_SCHEDULER", "false").lower() == "true"

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True


class TestingConfig(Config):
    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    START_SCHEDULER = False


CONFIG_MAP = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
