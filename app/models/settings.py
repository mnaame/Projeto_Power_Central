from app.extensions import db
from app.models.types import TZDateTime
from app.utils.time import utcnow


class Setting(db.Model):
    """Configuração chave-valor editável pela interface (RF7/RF6).

    Valores sensíveis (ex.: token do Telegram) são gravados cifrados pela
    camada de serviço; este modelo apenas armazena texto opaco.
    """

    __tablename__ = "settings"

    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text, nullable=True)
    updated_at = db.Column(TZDateTime, nullable=False, default=utcnow, onupdate=utcnow)
    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Setting {self.key}>"
