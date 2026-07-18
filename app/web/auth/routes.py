from __future__ import annotations

from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db, limiter
from app.models.user import User
from app.security import verify_password
from app.services import audit_service
from app.utils.time import utcnow
from app.web.auth.forms import LoginForm

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    form = LoginForm()
    erro = None

    if form.validate_on_submit():
        username = form.username.data.strip()
        usuario = User.query.filter_by(username=username).first()
        autenticado = (
            usuario is not None
            and usuario.active
            and verify_password(usuario.password_hash, form.password.data)
        )

        if autenticado:
            usuario.last_login_at = utcnow()
            login_user(usuario)
            audit_service.registrar(action="login", result="success", user=usuario)
            db.session.commit()
            return redirect(url_for("dashboard.index"))

        audit_service.registrar(action="login", result="failure", username_attempted=username)
        db.session.commit()
        erro = "Usuário ou senha inválidos."

    return render_template("auth/login.html", form=form, erro=erro)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    audit_service.registrar(action="logout", result="success", user=current_user)
    db.session.commit()
    logout_user()
    return redirect(url_for("auth.login"))
