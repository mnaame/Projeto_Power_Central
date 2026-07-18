from __future__ import annotations

from functools import wraps

from flask import abort, request
from flask_login import current_user

from app.extensions import db
from app.services import audit_service


def roles_required(*roles: str):
    """Restringe a rota aos papéis informados (RF3). Acesso negado gera
    403 e fica registrado em auditoria (critério de aceite: "Operador não
    acessa telas de admin; tentativa fica na auditoria")."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)

            if current_user.role not in roles:
                audit_service.registrar(
                    action="unauthorized_access_attempt",
                    result="failure",
                    user=current_user,
                    details={"required_roles": list(roles), "path": request.path},
                )
                db.session.commit()
                abort(403)

            return view(*args, **kwargs)

        return wrapped

    return decorator
