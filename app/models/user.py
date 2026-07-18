from flask_login import UserMixin

from app.extensions import db
from app.models.types import TZDateTime
from app.utils.time import utcnow

ROLES = ("admin", "operador")


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(16), nullable=False, default="operador")
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(TZDateTime, nullable=False, default=utcnow)
    last_login_at = db.Column(TZDateTime, nullable=True)

    __table_args__ = (
        db.CheckConstraint("role IN ('admin', 'operador')", name="ck_users_role"),
    )

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_active(self) -> bool:  # sobrepõe o padrão (sempre True) do UserMixin
        return self.active

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.username} ({self.role})>"
