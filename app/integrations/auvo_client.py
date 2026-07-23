"""Client da API da Auvo v2 (abertura de tarefas para despacho de técnico).

Envelopa o motor validado em produção do protótipo (`auvo.py` dos
scripts): mesma sequência de login (GET /login → Bearer JWT de 30 min,
renovado com margem de 5 min), mesmos fallbacks de extração de
token/lista/total (a Auvo aninha tudo em `result`), mesmos timeouts e as
mesmas coerções de tipo que custaram um erro real cada até acertar —
`customerId`/`taskType`/`priority`/ids como NÚMERO (string quebra a Auvo
com 500) e prioridade numérica (1/2/3).

Segue o padrão do telegram_client: exceção dedicada (`AuvoError`) que o
chamador registra — nunca propaga como crash do coletor. Em erro de
criação, a exceção carrega o corpo enviado e a resposta, para o
histórico de chamados (diagnóstico foi o que destravou a integração).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests

logger = logging.getLogger("auvo")

BASE_PADRAO = "https://api.auvo.com.br/v2"
VALIDADE_TOKEN_SEGUNDOS = 25 * 60  # renova antes dos 30 min oficiais
PAGE_SIZE_PADRAO = 50  # 100 pode dar timeout (validado)

TIMEOUT_LOGIN = 30
TIMEOUT_LISTAS = 120
TIMEOUT_TAREFA = 60

# Campos que a Auvo exige como número — enviar string dá 400/500.
_CAMPOS_INTEIROS = ("customerId", "taskType", "priority", "idUserFrom", "idUserTo", "teamId")


class AuvoError(Exception):
    """Erro em chamada à Auvo. Carrega o que foi enviado e o que voltou,
    para o histórico de chamados registrar e permitir diagnóstico."""

    def __init__(
        self,
        mensagem: str,
        *,
        status: int | None = None,
        corpo_enviado: dict | None = None,
        resposta: object = None,
    ):
        super().__init__(mensagem)
        self.status = status
        self.corpo_enviado = corpo_enviado
        self.resposta = resposta


@dataclass(frozen=True)
class AuvoCredentials:
    api_key: str
    api_token: str
    base_url: str = BASE_PADRAO


class AuvoClient:
    def __init__(
        self,
        credentials: AuvoCredentials,
        *,
        clock: Callable[[], float] = time.time,
        session: requests.Session | None = None,
    ):
        self._credentials = credentials
        self._clock = clock
        self._session = session or requests.Session()
        self._token: str | None = None
        self._expira = 0.0

    @property
    def base_url(self) -> str:
        return self._credentials.base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Autenticação
    # ------------------------------------------------------------------

    def login(self) -> str:
        """Troca apiKey/apiToken pelo Bearer JWT (30 min). O token vem em
        `result.accessToken`; fallbacks preservados do motor validado."""
        try:
            response = self._session.get(
                f"{self.base_url}/login/",
                params={
                    "apiKey": self._credentials.api_key,
                    "apiToken": self._credentials.api_token,
                },
                timeout=TIMEOUT_LOGIN,
            )
        except requests.RequestException as exc:
            raise AuvoError(f"Login Auvo: falha de rede: {exc}") from exc

        try:
            dados = response.json()
        except ValueError as exc:
            raise AuvoError(
                f"Login Auvo: resposta não-JSON (HTTP {response.status_code})",
                status=response.status_code,
                resposta=response.text[:500],
            ) from exc

        token = None
        for caminho in (
            ("result", "accessToken"),
            ("result", "access_token"),
            ("accessToken",),
            ("token",),
        ):
            no: object = dados
            for chave in caminho:
                no = no.get(chave) if isinstance(no, dict) else None
            if no:
                token = no
                break
        if not token:
            raise AuvoError(
                "Login Auvo: token não encontrado na resposta.",
                status=response.status_code,
                resposta=dados,
            )

        self._token = str(token)
        self._expira = self._clock() + VALIDADE_TOKEN_SEGUNDOS
        return self._token

    def _cabecalho(self) -> dict[str, str]:
        if not self._token or self._clock() >= self._expira:
            self.login()
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _request(self, metodo: str, path: str, **kwargs) -> requests.Response:
        """Chamada autenticada com uma repetição em 401 (token pode ter
        sido invalidado antes da margem de renovação)."""
        url = f"{self.base_url}{path}"
        try:
            response = self._session.request(
                metodo, url, headers=self._cabecalho(), **kwargs
            )
            if response.status_code == 401:
                logger.info("Auvo devolveu 401 — refazendo login e repetindo.")
                self.login()
                response = self._session.request(
                    metodo, url, headers=self._cabecalho(), **kwargs
                )
        except requests.RequestException as exc:
            raise AuvoError(f"Auvo {path}: falha de rede: {exc}") from exc
        return response

    # ------------------------------------------------------------------
    # Listas (paramFilter obrigatório, páginas de 50)
    # ------------------------------------------------------------------

    def _listar_paginado(self, path: str, *, page_size: int = PAGE_SIZE_PADRAO) -> list[dict]:
        itens: list[dict] = []
        pagina = 1
        while True:
            response = self._request(
                "GET",
                path,
                params={"paramFilter": "{}", "page": pagina, "pageSize": page_size},
                timeout=TIMEOUT_LISTAS,
            )
            if response.status_code >= 300:
                raise AuvoError(
                    f"Auvo {path} devolveu HTTP {response.status_code}.",
                    status=response.status_code,
                    resposta=_texto(response),
                )
            dados = response.json()
            lote = _extrair_lista(dados)
            itens.extend(lote)
            total = _total_itens(dados)
            if not lote or len(lote) < page_size or (total and len(itens) >= total):
                break
            pagina += 1
        return itens

    def listar_clientes(self) -> list[dict]:
        return self._listar_paginado("/customers/")

    def listar_usuarios(self) -> list[dict]:
        return self._listar_paginado("/users/")

    def listar_tipos_tarefa(self) -> list[dict]:
        return self._listar_paginado("/taskTypes/")

    # ------------------------------------------------------------------
    # Tarefas
    # ------------------------------------------------------------------

    def criar_tarefa(self, payload: dict[str, Any]) -> dict:
        """POST /tasks/ — sucesso é HTTP 201. O payload vem pronto do
        serviço (templates/regras são de lá); aqui só garantimos os tipos
        que a Auvo exige como número, antes de qualquer chamada."""
        corpo = dict(payload)
        for campo in _CAMPOS_INTEIROS:
            if campo in corpo and corpo[campo] is not None:
                try:
                    corpo[campo] = int(str(corpo[campo]).strip())
                except (TypeError, ValueError):
                    raise AuvoError(
                        f"Campo {campo} precisa ser numérico para a Auvo "
                        f"(recebido: {corpo[campo]!r}).",
                        corpo_enviado=corpo,
                    ) from None

        response = self._request("POST", "/tasks/", json=corpo, timeout=TIMEOUT_TAREFA)
        if response.status_code >= 300:
            raise AuvoError(
                f"Auvo recusou a criação da tarefa (HTTP {response.status_code}).",
                status=response.status_code,
                corpo_enviado=corpo,
                resposta=_texto(response),
            )
        return response.json() if _tem_json(response) else {}


# ----------------------------------------------------------------------
# Auxiliares de envelope (a Auvo aninha tudo em `result`) — preservados
# do motor validado em produção.
# ----------------------------------------------------------------------


def _extrair_lista(dados: object) -> list[dict]:
    if isinstance(dados, list):
        return dados
    if isinstance(dados, dict):
        res = dados.get("result", dados)
        if isinstance(res, list):
            return res
        if isinstance(res, dict):
            for chave in ("entityList", "list", "items", "data"):
                if isinstance(res.get(chave), list):
                    return res[chave]
    return []


def _total_itens(dados: object) -> int | None:
    if isinstance(dados, dict):
        res = dados.get("result", dados)
        if isinstance(res, dict):
            paged = res.get("pagedSearchReturnData") or res
            for chave in ("totalItems", "totalItens", "total", "count"):
                valor = paged.get(chave) if isinstance(paged, dict) else None
                if isinstance(valor, int):
                    return valor
    return None


def _tem_json(response: requests.Response) -> bool:
    return "application/json" in response.headers.get("Content-Type", "")


def _texto(response: requests.Response) -> object:
    try:
        return response.json()
    except ValueError:
        return response.text[:500]
