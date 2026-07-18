from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

logger = logging.getLogger("telegram")

API_BASE = "https://api.telegram.org"
LIMITE_CARACTERES = 4096
DEFAULT_TIMEOUT_SECONDS = 10


class TelegramError(Exception):
    """Erro ao enviar mensagem pelo Bot API do Telegram. Quem chama decide
    como registrar — nunca deve propagar como crash do coletor."""


@dataclass(frozen=True)
class TelegramCredentials:
    bot_token: str
    chat_id: str


class TelegramClient:
    def __init__(
        self, credentials: TelegramCredentials, *, timeout: float = DEFAULT_TIMEOUT_SECONDS
    ):
        self._credentials = credentials
        self._timeout = timeout

    def enviar_mensagem(self, texto_html: str) -> list[str]:
        """Envia texto_html como uma ou mais mensagens (parse_mode=HTML),
        dividindo em partes de até 4096 caracteres (regra RF6). Retorna os
        IDs das mensagens enviadas, na ordem."""
        return [self._enviar_parte(parte) for parte in dividir_mensagem(texto_html)]

    def _enviar_parte(self, parte: str) -> str:
        url = f"{API_BASE}/bot{self._credentials.bot_token}/sendMessage"
        try:
            response = requests.post(
                url,
                data={
                    "chat_id": self._credentials.chat_id,
                    "text": parte,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": "true",
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise TelegramError(f"Falha ao enviar mensagem ao Telegram: {exc}") from exc
        except ValueError as exc:
            raise TelegramError(f"Resposta não-JSON do Telegram: {exc}") from exc

        if not payload.get("ok"):
            raise TelegramError(f"Telegram recusou a mensagem: {payload!r}")

        return str(payload["result"]["message_id"])


def dividir_mensagem(texto: str, limite: int = LIMITE_CARACTERES) -> list[str]:
    """Divide um texto em partes de até `limite` caracteres, preferindo
    cortar em quebras de linha para não partir uma tag HTML ao meio."""
    if len(texto) <= limite:
        return [texto]

    partes: list[str] = []
    restante = texto
    while len(restante) > limite:
        corte = restante.rfind("\n", 0, limite)
        if corte <= 0:
            corte = limite
        partes.append(restante[:corte])
        restante = restante[corte:].lstrip("\n")
    if restante:
        partes.append(restante)
    return partes
