from __future__ import annotations

from flask import has_request_context, request

from app.extensions import db
from app.models.audit import AuditLog
from app.models.user import User


def _ip_atual() -> str | None:
    if not has_request_context():
        return None
    return request.headers.get("X-Forwarded-For", request.remote_addr)


def registrar(
    *,
    action: str,
    result: str,
    user: User | None = None,
    username_attempted: str | None = None,
    details: dict | None = None,
) -> AuditLog:
    """Grava um evento de auditoria (RF5): login/logout, atualização manual,
    mudança de configuração/usuários, tentativa de acesso sem permissão.
    Só é escrito aqui — não há edição/remoção pela interface."""
    entrada = AuditLog(
        action=action,
        result=result,
        user_id=user.id if user is not None else None,
        username_attempted=username_attempted or (user.username if user is not None else None),
        ip_address=_ip_atual(),
        details=details,
    )
    db.session.add(entrada)
    return entrada
