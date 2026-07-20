from app.config import Config, DevelopmentConfig, ProductionConfig


def test_production_config_does_not_force_secure_cookie():
    """Regressão: SESSION_COOKIE_SECURE precisa vir só do .env (via
    Config), nunca fixado em ProductionConfig. "production" não implica
    HTTPS — o serviço pode rodar em HTTP puro na rede local
    (-BindHost 0.0.0.0). Fixar True aqui já quebrou o cookie de sessão
    em produção real (CSRF "session token is missing" ao logar via IP
    de rede sem HTTPS)."""
    assert "SESSION_COOKIE_SECURE" not in ProductionConfig.__dict__
    assert "SESSION_COOKIE_SECURE" not in DevelopmentConfig.__dict__
    assert ProductionConfig.SESSION_COOKIE_SECURE == Config.SESSION_COOKIE_SECURE
