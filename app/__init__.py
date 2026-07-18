import os

from flask import Flask, render_template
from sqlalchemy import text

from app.config import CONFIG_MAP
from app.extensions import csrf, db, limiter, login_manager, migrate
from app.logging_config import configure_logging


def create_app(config_name: str | None = None) -> Flask:
    config_name = config_name or os.environ.get("FLASK_ENV", "development")
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder="web/templates",
        static_folder="web/static",
    )
    app.config.from_object(CONFIG_MAP[config_name])

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Faça login para continuar."
    login_manager.login_message_category = "info"

    configure_logging(app)

    from app import models  # noqa: F401  garante que o Alembic enxergue os modelos
    from app.models.cycle import CollectionCycle
    from app.models.watchdog import WatchdogState

    from app.cli import register_cli

    register_cli(app)

    from app.web import register_blueprints
    from app.web.filters import registrar_filtros

    register_blueprints(app)
    registrar_filtros(app)

    @app.errorhandler(401)
    def nao_autenticado(_erro):
        return render_template("errors/401.html"), 401

    @app.errorhandler(403)
    def acesso_negado(_erro):
        return render_template("errors/403.html"), 403

    if app.config.get("START_SCHEDULER"):
        from app.scheduler import iniciar

        iniciar(app)

    @app.route("/health")
    def health():
        try:
            db.session.execute(text("SELECT 1"))
            db_ok = True
        except Exception:  # pragma: no cover - caminho de indisponibilidade do banco
            db_ok = False

        ultimo_ciclo = (
            CollectionCycle.query.order_by(CollectionCycle.started_at.desc()).first()
            if db_ok
            else None
        )
        watchdog = WatchdogState.query.first() if db_ok else None

        status = "ok" if db_ok else "degraded"
        return {
            "status": status,
            "db_ok": db_ok,
            "last_cycle_at": ultimo_ciclo.finished_at.isoformat() if ultimo_ciclo and ultimo_ciclo.finished_at else None,
            "last_cycle_status": ultimo_ciclo.status if ultimo_ciclo else None,
            "watchdog_alert_active": watchdog.alert_active if watchdog else False,
        }, 200 if db_ok else 503

    return app
