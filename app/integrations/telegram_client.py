from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

logger = logging.getLogger("telegram")

API_BASE = "https://api.telegram.org"
LIMITE_CARACTERES = 4096
LIMITE_LEGENDA = 1024  # caption do sendDocument é bem menor que a mensagem
DEFAULT_TIMEOUT_SECONDS = 10

# Subir arquivo não é mandar uma linha de texto. Com 10s (o timeout das
# mensagens), o relatório de uma conta movimentada estourava no meio do
# upload: o técnico recebia o diagnóstico e o arquivo nunca chegava. O
# relatório de 15 dias de uma loja grande passa dos 20 MB numa rede
# interna, e 5 minutos é folga para isso sem prender o bot
# indefinidamente.
TIMEOUT_DOCUMENTO_SEGUNDOS = 300

# Teto do próprio Bot API para upload. Acima disso o Telegram recusa, e
# recusa DEPOIS de receber o arquivo inteiro — checar antes evita gastar
# minutos de upload para ouvir não.
LIMITE_DOCUMENTO_BYTES = 50 * 1024 * 1024


class TelegramError(Exception):
    """Erro ao enviar mensagem pelo Bot API do Telegram. Quem chama decide
    como registrar — nunca deve propagar como crash do coletor."""


class TelegramArquivoGrande(TelegramError):
    """Arquivo acima do teto do Telegram. Separado de `TelegramError`
    porque o conserto é outro: repetir não adianta, tem que pedir menos
    dias."""

    def __init__(self, tamanho: int):
        self.tamanho = tamanho
        super().__init__(
            f"Arquivo de {tamanho / 1024 / 1024:.1f} MB; o Telegram aceita até "
            f"{LIMITE_DOCUMENTO_BYTES // 1024 // 1024} MB."
        )


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

    def enviar_mensagem(self, texto_html: str, *, chat_id: str | None = None) -> list[str]:
        """Envia texto_html como uma ou mais mensagens (parse_mode=HTML),
        dividindo em partes de até 4096 caracteres (regra RF6). Retorna os
        IDs das mensagens enviadas, na ordem. `chat_id` responde num chat
        específico (o bot do técnico responde onde o comando foi pedido);
        sem ele, vai para o chat configurado — os alertas seguem iguais."""
        return [
            self._enviar_parte(parte, chat_id=chat_id)
            for parte in dividir_mensagem(texto_html)
        ]

    def _enviar_parte(self, parte: str, *, chat_id: str | None = None) -> str:
        url = f"{API_BASE}/bot{self._credentials.bot_token}/sendMessage"
        try:
            response = requests.post(
                url,
                data={
                    "chat_id": chat_id or self._credentials.chat_id,
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

    def buscar_updates(self, *, offset: int | None = None, timeout: int = 25) -> list[dict]:
        """Long polling (`getUpdates`): a conexão fica aberta até `timeout`
        segundos esperando mensagem. É o que permite o bot ESCUTAR sem o
        site precisar de URL pública (webhook exigiria HTTPS exposto).

        `offset` confirma os updates já processados — o Telegram para de
        reenviá-los. O timeout do HTTP é maior que o do long polling, senão
        a requisição morreria antes de a espera terminar."""
        url = f"{API_BASE}/bot{self._credentials.bot_token}/getUpdates"
        parametros: dict[str, object] = {"timeout": timeout}
        if offset is not None:
            parametros["offset"] = offset
        try:
            response = requests.get(
                url, params=parametros, timeout=self._timeout + timeout
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise TelegramError(f"Falha ao buscar updates do Telegram: {exc}") from exc
        except ValueError as exc:
            raise TelegramError(f"Resposta não-JSON do Telegram: {exc}") from exc

        if not payload.get("ok"):
            raise TelegramError(f"Telegram recusou o getUpdates: {payload!r}")
        return list(payload.get("result", []))

    def enviar_documento(
        self, conteudo: bytes, *, nome_arquivo: str, chat_id: str | None = None,
        legenda: str = "",
    ) -> str:
        """`sendDocument` — manda o arquivo do relatório para o técnico
        abrir no celular. A legenda vai junto (limite bem menor que o da
        mensagem: 1024), então quem chama manda só o resumo curto.

        Usa um timeout próprio, muito maior que o das mensagens: o que
        vale para mandar uma linha de texto não vale para subir dezenas de
        megabytes."""
        if len(conteudo) > LIMITE_DOCUMENTO_BYTES:
            raise TelegramArquivoGrande(len(conteudo))

        url = f"{API_BASE}/bot{self._credentials.bot_token}/sendDocument"
        dados: dict[str, str] = {"chat_id": chat_id or self._credentials.chat_id}
        if legenda:
            dados["caption"] = legenda[:LIMITE_LEGENDA]
            dados["parse_mode"] = "HTML"
        try:
            response = requests.post(
                url,
                data=dados,
                files={"document": (nome_arquivo, conteudo)},
                timeout=TIMEOUT_DOCUMENTO_SEGUNDOS,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise TelegramError(f"Falha ao enviar documento ao Telegram: {exc}") from exc
        except ValueError as exc:
            raise TelegramError(f"Resposta não-JSON do Telegram: {exc}") from exc

        if not payload.get("ok"):
            raise TelegramError(f"Telegram recusou o documento: {payload!r}")
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
