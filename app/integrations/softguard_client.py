from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence
from urllib.parse import urljoin

import requests

logger = logging.getLogger("softguard")

DESKTOP_APP_PATH = "/apps/Desktop/25.08.0/"
LOGIN_PATH = "/OAuthLogin.ashx"
TOKEN_VALID_PATH = "/rest/token/IsValid"
SEARCH_PATH = "/Rest/Search/CuentaByDealer"
HISTORICO_PATH = "/Rest/Search/ReporteHistorico"
TIMELINE_PATH = "/Rest/search/EventoTimeLineFull"
EXPORT_HISTORICO_PATH = "/handler/ExportReporteHistoricoExcel"
ZONA_PATH = "/Rest/Zona/"

# A tela de zoneamento pede 400 por página; a conta com mais zonas na base
# real não chega perto disso, mas o paginador cobre se passar.
PAGE_SIZE_ZONAS = 400
# Ordenação da própria tela — o portal já devolve na ordem certa, então o
# domínio não reordena (SP1/SP2 vêm depois das numéricas, como na tela).
ORDENACAO_ZONAS = [{"property": "orderCodigo", "direction": "ASC"}]

# Formato de data exigido por FechaDesde/FechaHasta do ReporteHistorico.
FORMATO_DATA_HISTORICO = "%m-%d-%Y %H:%M:%S"
# O export HTML (ExportReporteHistoricoExcel) usa um formato diferente —
# validado contra o motor de produção (relatorio_tecnico.py).
FORMATO_DATA_EXPORT = "%Y-%m-%d %H:%M:%S"

# Filtro de "todas as contas" (sem recorte de falha TST) — usado para
# montar o mapa número -> (id interno, nome) do relatório do técnico.
FILTRO_TODAS_CONTAS = [{"property": "cue_nparticion", "value": "0"}]

# Firma do dealer fixa nesta implantação (Novo Millenium) — usada no
# export do histórico (dealerFirma e prefixo de cuentanombre).
DEALER_FIRMA = "MIL"

DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = 2.0

# Filtro exato da tela "Falha TST" do portal (seção 5 do prompt).
FILTRO_FALHA_TST = [
    {"property": "cue_nparticion", "value": "0"},
    {"property": "_tip_nTipo:NOT", "value": "1,2,3,5,6,9,11"},
    {"property": "sta_ncuentaenfallo", "value": "1"},
]
ORDENACAO_PADRAO = [{"property": "cue_ncuenta", "direction": "ASC"}]


class SoftGuardError(Exception):
    """Erro de comunicação com o portal SoftGuard (indisponibilidade,
    timeout, resposta inesperada). Quem chama decide como registrar e
    alertar — nunca deve propagar como crash do processo."""


class SoftGuardAuthError(SoftGuardError):
    """Login rejeitado ou sessão inválida."""


@dataclass(frozen=True)
class SoftGuardCredentials:
    host: str
    port: str | int
    client_id: str
    username: str
    password: str

    @property
    def base_url(self) -> str:
        return f"https://{self.host}:{self.port}"


class SoftGuardClient:
    """Cliente HTTP puro (sem navegador) para a API interna do portal
    SoftGuard/PowerCentral — ver docs/ARQUITETURA.md seção 5 para o fluxo
    de login e o filtro exato da tela "Falha TST"."""

    def __init__(
        self,
        credentials: SoftGuardCredentials,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    ):
        self._credentials = credentials
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds
        self._session = requests.Session()
        self._logged_in = False

    @property
    def logged_in(self) -> bool:
        return self._logged_in

    def login(self) -> None:
        base = self._credentials.base_url
        self._request("GET", urljoin(base, DESKTOP_APP_PATH))

        self._request(
            "POST",
            urljoin(base, LOGIN_PATH),
            data={
                "ClientId": self._credentials.client_id,
                "cDealer": "",
                "username": self._credentials.username,
                "password": self._credentials.password,
                "x": "51",
                "y": "26",
            },
        )
        if "OAuth_Token" not in self._session.cookies:
            raise SoftGuardAuthError("Login não retornou o cookie OAuth_Token.")

        self._assert_session_valid()
        self._logged_in = True

    def _assert_session_valid(self) -> None:
        response = self._request("GET", urljoin(self._credentials.base_url, TOKEN_VALID_PATH))
        payload = self._json(response)
        if payload.get("Status") != 1:
            raise SoftGuardAuthError(f"Sessão inválida: {payload!r}")

    def _buscar_paginado(
        self, path: str, params_base: dict[str, Any], *, page_size: int
    ) -> list[dict[str, Any]]:
        """Loop de paginação page/start/limit até `total`, comum às
        consultas de busca do portal. Devolve as linhas cruas — parsing e
        regra de negócio são responsabilidade da camada de domínio."""
        if not self._logged_in:
            self.login()

        linhas: list[dict[str, Any]] = []
        start = 0
        total: int | None = None

        while total is None or start < total:
            params = dict(params_base)
            params.update(
                {"page": (start // page_size) + 1, "start": start, "limit": page_size}
            )
            response = self._request(
                "GET", urljoin(self._credentials.base_url, path), params=params
            )
            payload = self._json(response)
            total = int(payload.get("total", 0) or 0)
            # A API real devolve as linhas em "rows" (validado contra o
            # portal em produção); "data" fica como fallback defensivo.
            pagina = payload.get("rows", payload.get("data", []))
            linhas.extend(pagina)

            if not pagina:
                break
            start += page_size

        return linhas

    def buscar_contas_em_falha_tst(
        self, *, page_size: int = DEFAULT_PAGE_SIZE
    ) -> list[dict[str, Any]]:
        """Retorna todas as contas em falha de TST (paginação completa)."""
        return self._buscar_paginado(
            SEARCH_PATH,
            {"sort": json.dumps(ORDENACAO_PADRAO), "filter": json.dumps(FILTRO_FALHA_TST)},
            page_size=page_size,
        )

    def buscar_historico(
        self,
        *,
        codigos_alarme: Sequence[str],
        desde: datetime,
        hasta: datetime,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> list[dict[str, Any]]:
        """Consulta a tela "História do evento" (ReporteHistorico) para os
        códigos e o período dados. `desde`/`hasta` são usados como recebidos
        — ajustes de borda (+1s, folga de minutos) são de quem chama."""
        return self._buscar_paginado(
            HISTORICO_PATH,
            {
                "FechaDesde": desde.strftime(FORMATO_DATA_HISTORICO),
                "FechaHasta": hasta.strftime(FORMATO_DATA_HISTORICO),
                "CodigosAlarma": ",".join(codigos_alarme),
                "table": "p_recepcion",
                "OrdenarFecha": "DESC",
                "Mostrar": 5000,
            },
            page_size=page_size,
        )

    def listar_todas_contas(
        self, *, page_size: int = DEFAULT_PAGE_SIZE
    ) -> list[dict[str, Any]]:
        """Todas as contas do dealer (sem filtro de falha) — usado para
        montar o mapa número -> id interno (cue_iid) do relatório do
        técnico. O portal não busca por número; a lista inteira é
        carregada e filtrada em memória (mesmo padrão do motor validado
        em produção)."""
        return self._buscar_paginado(
            SEARCH_PATH,
            {"filter": json.dumps(FILTRO_TODAS_CONTAS)},
            page_size=page_size,
        )

    def listar_zonas(
        self, cue_iid: str | int, *, page_size: int = PAGE_SIZE_ZONAS
    ) -> list[dict[str, Any]]:
        """Zoneamento da conta (tela "Zonas" do portal). `cue_iid` é o mesmo
        id interno usado no export do histórico e no CuentaByDealer — aqui
        ele entra como `zon_iidcuenta`.

        Os dois primeiros filtros são os da própria tela: `LIKENOT PAR`
        tira as partições e `ISNOTNULLOREMPTYTRIM` tira as zonas vazias —
        juntos dão exatamente o "zoneamento completo" que o técnico vê."""
        filtro = [
            {"property": "zon_ccodigo:LIKENOT", "value": "PAR"},
            {"property": "zon_ccodigo:ISNOTNULLOREMPTYTRIM", "value": ""},
            {"property": "zon_iidcuenta", "value": cue_iid},
        ]
        return self._buscar_paginado(
            ZONA_PATH,
            {"filter": json.dumps(filtro), "sort": json.dumps(ORDENACAO_ZONAS)},
            page_size=page_size,
        )

    def exportar_historico_html(
        self,
        *,
        cue_iid: str | int,
        numero_conta: str,
        nome_cliente: str,
        desde: datetime,
        hasta: datetime,
        codigos_alarme: Sequence[str],
        timeout: float = 120,
    ) -> bytes:
        """Baixa o histórico da conta no formato NATIVO da plataforma —
        o mesmo arquivo do export manual: HTML que o Excel abre
        renderizando título, cores por tipo de evento e texto (extensão
        .xls). `token` vai na query como o valor do cookie OAuth_Token,
        diferente de todas as outras chamadas do client (que usam a
        sessão autenticada por cookie sozinha)."""
        if not self._logged_in:
            self.login()
        token = self._session.cookies.get("OAuth_Token", "")

        response = self._request(
            "GET",
            urljoin(self._credentials.base_url, EXPORT_HISTORICO_PATH),
            params={
                "token": token,
                "fechaProceso": "true",
                "fechahoraeventocheck": "true",
                "FechaDesde": desde.strftime(FORMATO_DATA_EXPORT),
                "FechaHasta": hasta.strftime(FORMATO_DATA_EXPORT),
                "TipoEvento": "",
                "Origen": "true",
                "Estado": "",
                "Codigoalarma": ",".join(codigos_alarme),
                "dealerFirma": DEALER_FIRMA,
                "TrackGuard": "true",
                "CuentaReporte": cue_iid,
                "CuentaNumero": numero_conta,
                "mostrar": 5000,
                "exportToExcel": "yes",
                "cuentanombre": f"{DEALER_FIRMA} - {nome_cliente}",
            },
            timeout=timeout,
        )

        texto = response.content.decode("utf-8", "replace").lower()
        if "no se encontr" in texto or "regularizar la situaci" in texto:
            raise SoftGuardError(
                "A PowerCentral recusou o export do histórico (página não "
                "encontrada) — verifique as permissões do usuário de "
                "integração no perfil da PowerCentral."
            )
        return response.content

    def buscar_timeline(self, id_evento: str | int, *, limit: int = 500) -> list[dict[str, Any]]:
        """Linha do tempo completa de um evento (EventoTimeLineFull)."""
        if not self._logged_in:
            self.login()

        response = self._request(
            "GET",
            urljoin(self._credentials.base_url, TIMELINE_PATH),
            params={"IdEvento": id_evento, "limit": limit},
        )
        payload = self._json(response)
        return payload.get("rows", payload.get("data", []))

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        timeout = kwargs.pop("timeout", self._timeout)
        ultima_excecao: Exception | None = None
        for tentativa in range(1, self._max_retries + 1):
            try:
                response = self._session.request(method, url, timeout=timeout, **kwargs)
                response.raise_for_status()
                # Reforça a captura de cookies da resposta na sessão (cobre a
                # troca de OAuth_Token no passo de login — ver seção 5).
                self._session.cookies.update(response.cookies)
                return response
            except requests.RequestException as exc:
                ultima_excecao = exc
                logger.warning(
                    "Falha ao acessar %s (tentativa %s/%s): %s",
                    url,
                    tentativa,
                    self._max_retries,
                    exc,
                )
                if tentativa < self._max_retries:
                    time.sleep(self._backoff_seconds * tentativa)
        raise SoftGuardError(f"Falha ao acessar {url}: {ultima_excecao}") from ultima_excecao

    @staticmethod
    def _json(response: requests.Response) -> dict[str, Any]:
        try:
            return response.json()
        except ValueError as exc:
            raise SoftGuardError(
                f"Resposta não-JSON de {response.url}: {response.text[:200]!r}"
            ) from exc
