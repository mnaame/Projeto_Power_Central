from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.extensions import db
from app.models.settings import Setting

# Valores padrão (regra 6.1/6.2 — seção 6 do prompt). RF7 permite ajustar
# pela interface; enquanto não houver linha em `settings`, vale o padrão.
DEFAULTS: dict[str, str] = {
    "window_hours": "3",
    "confirming_codes": "TST,CLO,OPN",
    "collector_interval_minutes": "5",
    "watchdog_threshold_minutes": "15",
    "manual_cooldown_seconds": "60",
    "retention_days": "90",
    "show_false_positives_in_panel": "true",
    "telegram_bot_token": "",
    "telegram_chat_id": "",
}

_TELEGRAM_TOKEN_KEY = "telegram_bot_token"
_TELEGRAM_CHAT_KEY = "telegram_chat_id"


def get(key: str) -> str:
    setting = db.session.get(Setting, key)
    if setting is not None and setting.value is not None:
        return setting.value
    return DEFAULTS.get(key, "")


def set(key: str, value: str, *, updated_by_id: int | None = None) -> Setting:
    setting = db.session.get(Setting, key)
    if setting is None:
        setting = Setting(key=key)
        db.session.add(setting)
    setting.value = value
    setting.updated_by_id = updated_by_id
    return setting


def get_window_hours() -> float:
    return float(get("window_hours"))


def get_confirming_codes() -> tuple[str, ...]:
    bruto = get("confirming_codes")
    return tuple(codigo.strip() for codigo in bruto.split(",") if codigo.strip())


def get_collector_interval_minutes() -> int:
    return int(get("collector_interval_minutes"))


def get_watchdog_threshold_minutes() -> float:
    return float(get("watchdog_threshold_minutes"))


def get_manual_cooldown_seconds() -> int:
    return int(get("manual_cooldown_seconds"))


def get_retention_days() -> int:
    return int(get("retention_days"))


def show_false_positives_in_panel() -> bool:
    return get("show_false_positives_in_panel").strip().lower() == "true"


def _fernet(encryption_key: str) -> Fernet:
    chave = encryption_key.encode() if isinstance(encryption_key, str) else encryption_key
    return Fernet(chave)


def set_telegram_credentials(
    bot_token: str, chat_id: str, *, encryption_key: str, updated_by_id: int | None = None
) -> None:
    cifra = _fernet(encryption_key)
    set(
        _TELEGRAM_TOKEN_KEY,
        cifra.encrypt(bot_token.encode()).decode(),
        updated_by_id=updated_by_id,
    )
    set(
        _TELEGRAM_CHAT_KEY,
        cifra.encrypt(chat_id.encode()).decode(),
        updated_by_id=updated_by_id,
    )


def get_telegram_credentials(*, encryption_key: str) -> tuple[str, str] | None:
    """Retorna (bot_token, chat_id) decifrados, ou None se ainda não
    configurado ou se a chave de cifra não corresponder ao valor gravado."""
    token_cifrado = get(_TELEGRAM_TOKEN_KEY)
    chat_id_cifrado = get(_TELEGRAM_CHAT_KEY)
    if not token_cifrado or not chat_id_cifrado:
        return None

    cifra = _fernet(encryption_key)
    try:
        token = cifra.decrypt(token_cifrado.encode()).decode()
        chat_id = cifra.decrypt(chat_id_cifrado.encode()).decode()
    except InvalidToken:
        return None
    return token, chat_id
