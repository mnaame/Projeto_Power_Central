from __future__ import annotations

from pathlib import Path

from app.extensions import db, login_manager
from app.models.user import User


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))


def register_context(app) -> None:
    logo_path = Path(app.static_folder) / "img" / "logo.png"

    @app.context_processor
    def inject_branding():
        # Checado a cada request: basta salvar o arquivo da logo em
        # app/web/static/img/logo.png que ela aparece, sem reiniciar.
        return {"logo_disponivel": logo_path.exists()}


def register_blueprints(app) -> None:
    from app.web.admin.routes import bp as admin_bp
    from app.web.auth.routes import bp as auth_bp
    from app.web.auvo.routes import bp as auvo_bp
    from app.web.bi.routes import bp as bi_bp
    from app.web.central_cliente.routes import bp as central_cliente_bp
    from app.web.cofre.routes import bp as cofre_bp
    from app.web.dashboard.routes import bp as dashboard_bp
    from app.web.reports.routes import bp as reports_bp
    from app.web.tarefas.routes import bp as tarefas_bp
    from app.web.tecnico.routes import bp as tecnico_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(auvo_bp)
    app.register_blueprint(tecnico_bp)
    app.register_blueprint(bi_bp)
    app.register_blueprint(cofre_bp)
    app.register_blueprint(central_cliente_bp)
    app.register_blueprint(tarefas_bp)
