import os

from flask import Flask
from sqlalchemy import text

from app.config import CONFIG_MAP
from app.extensions import db, migrate
from app.logging_config import configure_logging


def create_app(config_name: str | None = None) -> Flask:
    config_name = config_name or os.environ.get("FLASK_ENV", "development")
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(CONFIG_MAP[config_name])

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)

    configure_logging(app)

    from app import models  # noqa: F401  garante que o Alembic enxergue os modelos

    from app.cli import register_cli

    register_cli(app)

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
        status = "ok" if db_ok else "degraded"
        return {"status": status, "db_ok": db_ok}, 200 if db_ok else 503

    return app
