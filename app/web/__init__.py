from __future__ import annotations

from app.extensions import db, login_manager
from app.models.user import User


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))


def register_blueprints(app) -> None:
    from app.web.auth.routes import bp as auth_bp
    from app.web.dashboard.routes import bp as dashboard_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
