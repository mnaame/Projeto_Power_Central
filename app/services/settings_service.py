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
    "periodic_report_enabled": "false",
    "periodic_report_interval_minutes": "60",
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    # Módulo Atendimentos (A.5)
    "atend_codigos_evento": "NYE,NYC",
    "atend_incluir_automaticos": "false",
    "atend_incluir_abertos": "false",
    "atend_resolucao_indica_arme": "ativado,armado remotamente,armamento confirmado",
    # Módulo Disparos (B.5)
    "disp_horas_primeira_execucao": "24",
    "disp_limite_recorrente": "15",
    "disp_ignorar_zonas": "PANICO",
    # Módulo Disparos Geral (fim de semana)
    "dispg_limite_recorrente": "50",
    "dispg_grupo_villefort": "VILLEFORT",
    "dispg_grupo_super_nosso": "SUPER NOSSO,APOIO",
    # Módulo Chamados Auvo (§4/§5 do complemento) — simulação LIGADA por
    # padrão: só desligar depois de validar de-para e payload.
    "auvo_api_key": "",
    "auvo_api_token": "",
    "auvo_simulacao": "true",
    "auvo_criador_id": "",
    "auvo_responsavel_id": "",
    "auvo_atribuir_responsavel": "true",
    "auvo_task_type": "",
    "auvo_priority": "2",
    "auvo_cooldown_horas": "12",
    "auvo_sem_comunicacao_horas_minimas": "3",
    "auvo_disparos_minimos_tarefa": "5",
    "auvo_template_semcom_titulo": "Cliente sem comunicacao - {conta} {nome}",
    "auvo_template_semcom_descricao": (
        "Cliente sem comunicacao desde {desde}. "
        "Ultimo evento recebido: {sinal}. Verificar em campo."
    ),
    "auvo_template_disparos_titulo": "Disparos aleatorios - {conta} {nome}",
    "auvo_template_disparos_descricao": (
        "{qtd} disparo(s) aleatorio(s) no periodo. "
        "Zonas: {zonas}. Avaliar sensores/instalacao."
    ),
}

_TELEGRAM_TOKEN_KEY = "telegram_bot_token"
_TELEGRAM_CHAT_KEY = "telegram_chat_id"
_AUVO_KEY_KEY = "auvo_api_key"
_AUVO_TOKEN_KEY = "auvo_api_token"


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


def periodic_report_enabled() -> bool:
    return get("periodic_report_enabled").strip().lower() == "true"


def get_periodic_report_interval_minutes() -> int:
    return int(get("periodic_report_interval_minutes"))


def _lista(chave: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in get(chave).split(",") if item.strip())


# --- Módulo Atendimentos (A.5) ---


def get_atend_codigos_evento() -> tuple[str, ...]:
    return _lista("atend_codigos_evento")


def atend_incluir_automaticos() -> bool:
    return get("atend_incluir_automaticos").strip().lower() == "true"


def atend_incluir_abertos() -> bool:
    return get("atend_incluir_abertos").strip().lower() == "true"


def get_atend_resolucao_indica_arme() -> tuple[str, ...]:
    return _lista("atend_resolucao_indica_arme")


# --- Módulo Disparos (B.5) ---


def get_disp_horas_primeira_execucao() -> int:
    return int(get("disp_horas_primeira_execucao"))


def get_disp_limite_recorrente() -> int:
    return int(get("disp_limite_recorrente"))


def get_disp_ignorar_zonas() -> tuple[str, ...]:
    return _lista("disp_ignorar_zonas")


# --- Módulo Disparos Geral (fim de semana) ---


def get_dispg_limite_recorrente() -> int:
    return int(get("dispg_limite_recorrente"))


def get_dispg_grupo_villefort() -> tuple[str, ...]:
    return _lista("dispg_grupo_villefort")


def get_dispg_grupo_super_nosso() -> tuple[str, ...]:
    return _lista("dispg_grupo_super_nosso")


# --- Módulo Chamados Auvo ---


def auvo_simulacao() -> bool:
    return get("auvo_simulacao").strip().lower() == "true"


def _int_ou_none(chave: str) -> int | None:
    bruto = get(chave).strip()
    return int(bruto) if bruto else None


def get_auvo_criador_id() -> int | None:
    return _int_ou_none("auvo_criador_id")


def get_auvo_responsavel_id() -> int | None:
    return _int_ou_none("auvo_responsavel_id")


def auvo_atribuir_responsavel() -> bool:
    return get("auvo_atribuir_responsavel").strip().lower() == "true"


def get_auvo_task_type() -> int | None:
    return _int_ou_none("auvo_task_type")


def get_auvo_priority() -> int:
    return int(get("auvo_priority"))


def get_auvo_cooldown_horas() -> float:
    return float(get("auvo_cooldown_horas"))


def get_auvo_sem_comunicacao_horas_minimas() -> float:
    return float(get("auvo_sem_comunicacao_horas_minimas"))


def get_auvo_disparos_minimos_tarefa() -> int:
    return int(get("auvo_disparos_minimos_tarefa"))


def get_auvo_template(gatilho: str, parte: str) -> str:
    """gatilho: 'semcom' | 'disparos'; parte: 'titulo' | 'descricao'."""
    return get(f"auvo_template_{gatilho}_{parte}")


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


def set_auvo_credentials(
    api_key: str, api_token: str, *, encryption_key: str, updated_by_id: int | None = None
) -> None:
    """Grava apiKey/apiToken da Auvo cifrados (mesmo mecanismo do
    Telegram) — segredos nunca em claro no banco nem no repositório."""
    cifra = _fernet(encryption_key)
    set(_AUVO_KEY_KEY, cifra.encrypt(api_key.encode()).decode(), updated_by_id=updated_by_id)
    set(_AUVO_TOKEN_KEY, cifra.encrypt(api_token.encode()).decode(), updated_by_id=updated_by_id)


def get_auvo_credentials(*, encryption_key: str) -> tuple[str, str] | None:
    """Retorna (api_key, api_token) decifrados, ou None se ainda não
    configurado ou se a chave de cifra não corresponder."""
    key_cifrada = get(_AUVO_KEY_KEY)
    token_cifrado = get(_AUVO_TOKEN_KEY)
    if not key_cifrada or not token_cifrado:
        return None

    cifra = _fernet(encryption_key)
    try:
        api_key = cifra.decrypt(key_cifrada.encode()).decode()
        api_token = cifra.decrypt(token_cifrado.encode()).decode()
    except InvalidToken:
        return None
    return api_key, api_token
