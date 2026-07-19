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
    from app.web.dashboard.routes import bp as dashboard_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp)
