"""Cliente ISOLADO do endpoint interno (não-oficial) do painel da Auvo —
usado só pelo módulo Links da Central do Cliente. Autentica por cookie de
sessão do painel (não pela API oficial v2, que fica em `auvo_client.py`).
Isolado de propósito: quando a Auvo mudar esse endpoint sem aviso (é de
fato não documentado), o dano fica contido neste arquivo — ver
docs/CENTRAL_CLIENTE.md §6 para o playbook de reparo.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

BASE_PADRAO = "https://app3.auvo.com.br"
PATH_SALVAR_CONTATO = "/AdicionarTarefa/SalvarContatoAdicionadoPeloModalNotificacoes"
TIMEOUT_PADRAO = 30


class CentralClientePainelError(Exception):
    """Erro genérico ao chamar o endpoint interno do painel."""


class CentralClienteCookieExpiradoError(CentralClientePainelError):
    """Cookie de sessão vencido (ou usuário errado): a Auvo devolveu HTML
    de login em vez do JSON de sucesso esperado. Quem chama deve abortar
    o lote inteiro aqui — nada a partir deste ponto deve ser marcado como
    criado."""


@dataclass(frozen=True)
class PainelCredentials:
    """Colada pelo admin a cada execução — nunca persistida em claro (ver
    docs/CENTRAL_CLIENTE.md §5)."""

    cookie: str
    auvo_user_request: str
    base_url: str = BASE_PADRAO


class CentralClientePainelClient:
    def __init__(
        self,
        credentials: PainelCredentials,
        *,
        session: requests.Session | None = None,
        timeout: float = TIMEOUT_PADRAO,
    ):
        self._credentials = credentials
        self._session = session or requests.Session()
        self._timeout = timeout

    def criar_contato_link(
        self,
        *,
        nome: str,
        cargo: str,
        telefone: str = "",
        email: str = "",
        receber_notificacao: bool = False,
        login: str = "",
        senha: str = "",
        link_acesso: str,
        habilita_menu_solicitacoes: bool,
        habilita_menu_os: bool,
        habilita_menu_orcamento: bool,
        codigo_cliente: int,
        codigo: int = 0,
    ) -> int:
        """Cria (codigo=0) ou atualiza (codigo existente) um contato com
        link de acesso. Devolve o `codigo` do contato. Levanta
        `CentralClienteCookieExpiradoError` se a resposta não for o JSON
        de sucesso esperado, ou `CentralClientePainelError` para qualquer
        outra falha (inclusive recusa explícita da Auvo)."""
        payload = {
            "Nome": nome,
            "Cargo": cargo,
            "Telefone": telefone,
            "Email": email,
            "ReceberNotificacao": "true" if receber_notificacao else "false",
            "Login": login,
            "Senha": senha,
            "LinkAcesso": link_acesso,
            "HabilitaMenuSolicitacoes": "true" if habilita_menu_solicitacoes else "false",
            "HabilitaMenuOS": "true" if habilita_menu_os else "false",
            "HabilitaMenuOrcamento": "true" if habilita_menu_orcamento else "false",
            "CodigoCliente": codigo_cliente,
            "Codigo": codigo,
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "auvo-user-request": self._credentials.auvo_user_request,
            "Cookie": self._credentials.cookie,
        }
        url = f"{self._credentials.base_url.rstrip('/')}{PATH_SALVAR_CONTATO}"

        try:
            response = self._session.post(
                url, data=payload, headers=headers, timeout=self._timeout
            )
        except requests.RequestException as exc:
            raise CentralClientePainelError(f"Falha de rede ao criar contato: {exc}") from exc

        # Cookie vencido -> a Auvo redireciona para a tela de login (HTML),
        # não devolve o JSON esperado. É o único sinal disponível.
        if "application/json" not in response.headers.get("Content-Type", ""):
            raise CentralClienteCookieExpiradoError(
                "Resposta não é JSON (provável cookie de sessão vencido) — "
                "capture um cookie novo pelo F12 e tente de novo."
            )
        try:
            dados = response.json()
        except ValueError as exc:
            raise CentralClienteCookieExpiradoError(
                "Resposta não é JSON válido (provável cookie de sessão vencido)."
            ) from exc

        if not isinstance(dados, dict) or "success" not in dados:
            raise CentralClienteCookieExpiradoError(
                "Resposta sem o campo 'success' esperado (provável cookie de sessão vencido)."
            )
        if not dados.get("success"):
            raise CentralClientePainelError(
                f"A Auvo recusou a criação do contato: {dados.get('mensagem') or dados!r}"
            )

        codigo_criado = dados.get("codigo")
        if codigo_criado is None:
            raise CentralClientePainelError(f"Resposta de sucesso sem 'codigo': {dados!r}")
        return int(codigo_criado)
