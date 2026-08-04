import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-change-me")
    ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY")
    # Chave dedicada do Cofre de Senhas — separada da ENCRYPTION_KEY geral
    # de propósito (um vazamento de uma não compromete a outra). Perder
    # esta chave torna as senhas do cofre irrecuperáveis (é assim que
    # cifra funciona) — ver docs/OPERACAO.md para orientação de backup.
    VAULT_ENCRYPTION_KEY = os.environ.get("VAULT_ENCRYPTION_KEY")

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
    # SESSION_COOKIE_SECURE NÃO é fixado aqui de propósito — segue o que
    # vier do .env (padrão "false"). "production" não implica HTTPS: o
    # serviço pode ficar em HTTP puro na rede local (-BindHost 0.0.0.0,
    # ver scripts/install_service.ps1) ou atrás de HTTPS de verdade
    # (Caddy/Cloudflare Tunnel). Fixar True aqui quebrava o cookie de
    # sessão sempre que "production" rodasse sem HTTPS na frente.


class TestingConfig(Config):
    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    START_SCHEDULER = False
    RATELIMIT_ENABLED = False
    # Chaves Fernet fixas só para testes — nunca usar em produção.
    ENCRYPTION_KEY = "DPmdqP8812octmZoWCmLjRSJg8b2xHd1-sTRyY64Rd0="
    # Deliberadamente DIFERENTE da ENCRYPTION_KEY acima — prova em teste
    # que as duas chaves são isoladas (ver test_cofre_service.py).
    VAULT_ENCRYPTION_KEY = "obMnHf1JEwOq0dt1z4R2I1Jhbd3QQdnXVrcHkLj7ia8="


CONFIG_MAP = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
