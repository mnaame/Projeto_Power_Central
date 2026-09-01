"""Bot do técnico no Telegram: o lado que ESCUTA.

O `TelegramClient` já era usado para empurrar alertas; aqui ele passa a
receber comandos por long polling (`getUpdates`) — escolha deliberada
sobre webhook, porque o site é local e não tem URL pública com HTTPS.

Postura de segurança (o que este módulo entrega é dado sensível — o
zoneamento é o mapa de sensores do cliente e o histórico é a rotina dele):

- só IDs de usuário do Telegram na lista `bot_tecnicos_ids` são atendidos;
  autoriza-se por QUEM ENVIOU, nunca pelo grupo (alguém pode ser
  adicionado a um grupo autorizado);
- toda tentativa, autorizada ou não, vai para a auditoria — sem o conteúdo
  do zoneamento/histórico no `details`;
- cooldown por usuário, para um comando repetido não abrir dezenas de
  consultas pesadas no portal em sequência.

Resiliência: exceção tratando um comando nunca derruba o loop (registra e
segue, mesma disciplina do coletor).
"""

from __future__ import annotations

import html
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from app.domain import bot_comandos as dom_bot
from app.domain import contas as dom_contas
from app.domain import tecnico as dom_tecnico
from app.domain import zoneamento as dom_zona
from app.domain.dates import FUSO_HORARIO
from app.extensions import db
from app.integrations.softguard_client import SoftGuardAuthError, SoftGuardClient, SoftGuardError
from app.integrations.telegram_client import (
    LIMITE_CARACTERES,
    TelegramError,
    dividir_mensagem,
)
from app.services import audit_service, collector, settings_service

logger = logging.getLogger("telegram_bot")

# Espera do long polling. A conexão fica aberta até chegar mensagem; um
# valor alto reduz requisições sem atrasar a resposta ao técnico.
TIMEOUT_POLLING_SEGUNDOS = 25
# Pausa entre voltas quando o bot está desligado ou o Telegram falhou —
# não adianta martelar.
PAUSA_OCIOSA_SEGUNDOS = 15
PAUSA_ERRO_SEGUNDOS = 30

# Margem para as tags <pre> caberem junto com o texto no limite do Telegram.
_MARGEM_PRE = 64

# Último pedido de cada usuário (id do Telegram -> monotonic). Em memória
# de propósito: cooldown é anti-abuso momentâneo, não precisa sobreviver a
# reinício, e assim não gera escrita no banco a cada comando.
_ultimo_pedido: dict[int, float] = {}
_lock_cooldown = threading.Lock()

_parar = threading.Event()
_thread: threading.Thread | None = None


# ----------------------------------------------------------------------
# Autorização e cooldown
# ----------------------------------------------------------------------


def autorizado(user_id: int | None) -> bool:
    return user_id is not None and user_id in settings_service.get_bot_tecnicos_ids()


def _segundos_restantes_de_cooldown(user_id: int, cooldown: int) -> int:
    if cooldown <= 0:
        return 0
    agora = time.monotonic()
    with _lock_cooldown:
        anterior = _ultimo_pedido.get(user_id)
        if anterior is not None and agora - anterior < cooldown:
            return int(cooldown - (agora - anterior)) + 1
        _ultimo_pedido[user_id] = agora
    return 0


def limpar_cooldowns() -> None:
    """Usado pelos testes — o estado é de processo, não de requisição."""
    with _lock_cooldown:
        _ultimo_pedido.clear()


# ----------------------------------------------------------------------
# Envio
# ----------------------------------------------------------------------


def _mensagens_monoespacadas(texto: str) -> list[str]:
    """Zoneamento é tabela: sem fonte monoespaçada as colunas desalinham no
    celular. Escapa ANTES de dividir para o corte considerar o tamanho já
    escapado, e envolve cada pedaço no seu próprio <pre> (um <pre> aberto
    em uma mensagem não continua na seguinte)."""
    escapado = html.escape(texto)
    return [
        f"<pre>{parte}</pre>"
        for parte in dividir_mensagem(escapado, LIMITE_CARACTERES - _MARGEM_PRE)
    ]


def _responder(telegram, chat_id: str, texto: str) -> None:
    telegram.enviar_mensagem(html.escape(texto), chat_id=chat_id)


# ----------------------------------------------------------------------
# Sessão SoftGuard reaproveitada entre comandos
# ----------------------------------------------------------------------


class _SessaoSoftGuard:
    """Mantém um `SoftGuardClient` logado entre comandos (relogar a cada
    pedido é lento e castiga o portal). O mapa de contas também é caro
    (lista inteira do dealer), então fica em cache com validade curta.

    **Sessão tem prazo.** O `SoftGuardClient` faz login uma vez e nunca
    reautentica sozinho (`_logged_in` só é setado na subida, e `_request`
    repete a chamada sem relogar). No resto do sistema isso nunca apareceu
    porque cada operação cria um client novo; aqui o client é
    reaproveitado, então um token vencido faria o portal responder 500 e a
    sessão morta ficaria em cache para sempre — foi exatamente o que
    aconteceu em produção. Por isso o client é descartado por idade, e
    quem chama ainda tem uma segunda linha de defesa em
    `_executar_renovando_sessao`."""

    VALIDADE_MAPA = timedelta(minutes=30)
    VALIDADE_SESSAO = timedelta(minutes=20)

    def __init__(self, config):
        self._config = config
        self._client: SoftGuardClient | None = None
        self._client_em: datetime | None = None
        self._mapa: list[dom_contas.Conta] | None = None
        self._mapa_em: datetime | None = None

    def client(self) -> SoftGuardClient:
        agora = datetime.now(timezone.utc)
        if (
            self._client is None
            or self._client_em is None
            or agora - self._client_em > self.VALIDADE_SESSAO
        ):
            self._client = SoftGuardClient(collector.credenciais_softguard(self._config))
            self._client_em = agora
        return self._client

    def invalidar(self) -> None:
        self._client = None
        self._client_em = None
        self._mapa = None
        self._mapa_em = None

    def contas(self) -> list[dom_contas.Conta]:
        """Todas as contas COM as partições — o bot é o único que precisa
        delas (o técnico trabalha no setor, não na conta inteira)."""
        agora = datetime.now(timezone.utc)
        if (
            self._mapa is None
            or self._mapa_em is None
            or agora - self._mapa_em > self.VALIDADE_MAPA
        ):
            self._mapa = dom_contas.contas_da_resposta(
                self.client().listar_todas_contas(incluir_particoes=True)
            )
            self._mapa_em = agora
        return self._mapa

    def contas_por_numero(self) -> dict[str, list[dom_contas.Conta]]:
        return dom_contas.agrupar_por_numero(self.contas())


# ----------------------------------------------------------------------
# Comandos
# ----------------------------------------------------------------------


def _executar_renovando_sessao(funcao, *, sessao):
    """Roda o comando; se o portal falhar, joga a sessão fora e tenta UMA
    vez com login novo.

    Existe porque a sessão do portal morre em silêncio: o token vence e o
    SoftGuard passa a responder **500**, não 401 — e o `SoftGuardClient`
    não relogá sozinho. Sem isto, a primeira expiração deixaria o bot
    mudo até alguém reiniciar o serviço (visto em produção).

    Seguro repetir: nada é enviado ao técnico antes das chamadas ao
    portal — as respostas de "não achei"/"qual?" retornam sem exceção, e
    o documento/zoneamento só sai depois que o portal respondeu."""
    try:
        return funcao()
    except SoftGuardError:
        logger.warning("Bot: portal falhou; renovando a sessão e tentando de novo.")
        sessao.invalidar()
        return funcao()


def _resolver_ou_avisar(termo: str, sessao, telegram, chat_id: str, *, comando: str):
    """Devolve a conta resolvida, ou None depois de já ter respondido ao
    técnico (não encontrada / ambígua / falta escolher a partição). Nunca
    chuta — nem o cliente, nem o setor."""
    resolucao = dom_bot.resolver_conta(termo, sessao.contas_por_numero())
    if resolucao.status == dom_bot.RESOLUCAO_OK:
        return resolucao.conta
    if resolucao.status == dom_bot.RESOLUCAO_AMBIGUA:
        _responder(telegram, chat_id, dom_bot.formatar_ambiguidade(resolucao.candidatas))
    elif resolucao.status == dom_bot.RESOLUCAO_PARTICOES:
        _responder(
            telegram, chat_id, dom_bot.formatar_particoes(resolucao.candidatas, comando=comando)
        )
    else:
        _responder(
            telegram,
            chat_id,
            f'Não achei nenhuma conta com "{termo}". '
            "Tente o número da conta (ex.: /zona 95) ou veja /clientes.",
        )
    return None


def _comando_zona(argumentos, *, sessao, telegram, chat_id: str) -> str:
    termo = " ".join(argumentos).strip()
    if not termo:
        _responder(telegram, chat_id, "Faltou a conta. Ex.: /zona 95")
        return ""

    conta = _resolver_ou_avisar(
        termo, sessao, telegram, chat_id, comando=dom_bot.COMANDO_ZONA
    )
    if conta is None:
        return ""

    zonas = dom_zona.zonas_da_resposta(sessao.client().listar_zonas(conta.cue_iid))
    texto = dom_zona.formatar_zoneamento(
        zonas, numero_conta=conta.identificacao, nome_cliente=conta.nome
    )
    for mensagem in _mensagens_monoespacadas(texto):
        telegram.enviar_mensagem(mensagem, chat_id=chat_id)
    _responder(telegram, chat_id, dom_bot.aviso_uso_interno())
    return conta.numero


def _comando_clientes(argumentos, *, sessao, telegram, chat_id: str) -> str:
    """Lista a base com as partições. Monoespaçado e quebrado em várias
    mensagens quando for grande (a base real passa de 100 linhas)."""
    filtro = " ".join(argumentos).strip()
    encontradas = dom_bot.filtrar_clientes(sessao.contas(), filtro)
    texto = dom_bot.formatar_lista_clientes(encontradas, filtro=filtro)
    for mensagem in _mensagens_monoespacadas(texto):
        telegram.enviar_mensagem(mensagem, chat_id=chat_id)
    if encontradas:
        _responder(telegram, chat_id, dom_bot.aviso_uso_interno())
    return ""


def _comando_relatorio(argumentos, *, sessao, telegram, chat_id: str) -> str:
    termo, dias_pedidos = dom_bot.separar_conta_e_dias(argumentos)
    if not termo:
        _responder(telegram, chat_id, "Faltou a conta. Ex.: /relatorio 95 7")
        return ""

    conta = _resolver_ou_avisar(
        termo, sessao, telegram, chat_id, comando=dom_bot.COMANDO_RELATORIO
    )
    if conta is None:
        return ""

    dias = dias_pedidos or settings_service.get_bot_relatorio_dias_padrao()
    codigos = settings_service.get_bot_relatorio_codigos()
    hasta = datetime.now(FUSO_HORARIO)
    desde = hasta - timedelta(days=dias)

    # UMA chamada só, e já filtrada pela conta. `buscar_historico` NÃO tem
    # filtro de conta: usá-lo aqui puxaria o histórico da base inteira
    # (todas as contas do dealer, em blocos de 100) só para contar os
    # eventos de uma loja — lento a ponto de estourar, e com o número
    # errado. O total sai do próprio arquivo que já vai para o técnico.
    conteudo = sessao.client().exportar_historico_html(
        cue_iid=conta.cue_iid,
        numero_conta=conta.numero,
        nome_cliente=conta.nome,
        desde=desde,
        hasta=hasta,
        codigos_alarme=codigos,
    )

    identificacao = conta.identificacao
    resumo = dom_bot.formatar_resumo_relatorio(
        numero_conta=identificacao,
        nome_cliente=conta.nome,
        dias=dias,
        total_eventos=dom_tecnico.contar_eventos_do_export(conteudo),
    )
    legenda = html.escape(f"{resumo}\n{dom_bot.aviso_uso_interno()}")

    # Os DOIS formatos, do mesmo conteúdo: o .xls nativo abre no PC com as
    # cores da plataforma; o PDF abre no celular sem app de planilha. Os
    # dois saem do mesmo `linhas_do_export`, então não há risco de um
    # mostrar coisa diferente do outro.
    base = dom_tecnico.nome_arquivo_loja(
        conta.numero, f"{conta.nome}{conta.sufixo_arquivo}", extensao=""
    )
    telegram.enviar_documento(
        conteudo, nome_arquivo=f"{base}xls", chat_id=chat_id, legenda=legenda
    )
    telegram.enviar_documento(
        dom_tecnico.montar_pdf_colorido(conteudo, titulo=f"{resumo.splitlines()[0]}"),
        nome_arquivo=f"{base}pdf",
        chat_id=chat_id,
    )
    return conta.numero


# ----------------------------------------------------------------------
# Despacho de um update
# ----------------------------------------------------------------------


def _dados_da_mensagem(update: dict) -> tuple[dict, str, int | None, str]:
    mensagem = update.get("message") or update.get("edited_message") or {}
    chat_id = str((mensagem.get("chat") or {}).get("id") or "")
    remetente = mensagem.get("from") or {}
    user_id = remetente.get("id")
    texto = mensagem.get("text") or ""
    return mensagem, chat_id, (int(user_id) if user_id is not None else None), texto


def processar_update(update: dict, *, config, sessao, telegram) -> None:
    """Trata um update. Erros de negócio viram resposta ao técnico; erros
    inesperados sobem para quem chama registrar (o loop nunca cai)."""
    _, chat_id, user_id, texto = _dados_da_mensagem(update)
    if not chat_id or not texto:
        return

    comando = dom_bot.interpretar(texto)
    if not comando.nome:
        return  # conversa solta no grupo: o bot não responde

    quem = {
        "telegram_user_id": user_id,
        "chat_id": chat_id,
        "comando": comando.nome,
        # O que foi pedido entra também nas FALHAS: sem isso, um erro do
        # portal não dizia sequer qual conta o técnico tinha pedido.
        "pedido": " ".join(comando.argumentos)[:100] or None,
    }

    if not autorizado(user_id):
        audit_service.registrar(
            action="bot_pedido_negado", result="failure", details=quem
        )
        db.session.commit()
        _responder(telegram, chat_id, "Sem permissão para usar este bot.")
        return

    if comando.nome == dom_bot.COMANDO_AJUDA:
        _responder(telegram, chat_id, dom_bot.formatar_ajuda())
        return

    espera = _segundos_restantes_de_cooldown(
        user_id, settings_service.get_bot_cooldown_segundos()
    )
    if espera:
        _responder(telegram, chat_id, f"Calma aí — tente de novo em {espera}s.")
        return

    acao = {
        dom_bot.COMANDO_ZONA: "bot_zona_pedido",
        dom_bot.COMANDO_CLIENTES: "bot_clientes_pedido",
        dom_bot.COMANDO_RELATORIO: "bot_relatorio_pedido",
    }[comando.nome]
    executores = {
        dom_bot.COMANDO_ZONA: _comando_zona,
        dom_bot.COMANDO_CLIENTES: _comando_clientes,
        dom_bot.COMANDO_RELATORIO: _comando_relatorio,
    }
    executor = executores[comando.nome]
    try:
        conta = _executar_renovando_sessao(
            lambda: executor(
                comando.argumentos, sessao=sessao, telegram=telegram, chat_id=chat_id
            ),
            sessao=sessao,
        )
    except SoftGuardAuthError:
        # Sessão do portal caiu: derruba o cache e pede pra tentar de novo
        # (relogar aqui no meio do comando esconderia o problema real).
        sessao.invalidar()
        audit_service.registrar(
            action=acao, result="failure", details={**quem, "erro": "sessao_softguard"}
        )
        db.session.commit()
        _responder(telegram, chat_id, "A sessão da PowerCentral caiu. Tente de novo.")
        return
    except SoftGuardError as exc:
        audit_service.registrar(
            action=acao, result="failure", details={**quem, "erro": str(exc)[:200]}
        )
        db.session.commit()
        # Export recusado é permissão do usuário de integração, não
        # indisponibilidade: mandar "tente de novo" faria o técnico
        # insistir num erro que nunca vai passar sozinho.
        if "recusou o export" in str(exc):
            _responder(
                telegram,
                chat_id,
                "A PowerCentral recusou o export deste histórico (permissão do "
                "usuário de integração). Avise o escritório — repetir não resolve.",
            )
        else:
            _responder(
                telegram, chat_id, "A PowerCentral não respondeu. Tente de novo em instantes."
            )
        return

    # `conta` vazia = pedido incompleto/ambíguo, já respondido ao técnico.
    audit_service.registrar(
        action=acao, result="success", details={**quem, "conta": conta or None}
    )
    db.session.commit()


# ----------------------------------------------------------------------
# Loop de long polling
# ----------------------------------------------------------------------


def _descartar_pendentes(telegram) -> None:
    """Ao (re)ligar o bot, confirma o que estiver na fila SEM executar. Sem
    isso, comandos parados há horas (o Telegram guarda ~24h) disparariam
    todos de uma vez na hora que alguém liga o bot na tela."""
    updates = telegram.buscar_updates(offset=None, timeout=0)
    if updates:
        settings_service.set_bot_update_offset(int(updates[-1]["update_id"]) + 1)
        db.session.commit()
        logger.info("Bot: %s update(s) pendente(s) descartado(s) ao ligar.", len(updates))


def _uma_volta(app, *, sessao_ref: dict) -> float:
    """Uma iteração do loop. Devolve quantos segundos dormir antes da
    próxima (o long polling já segura a conexão quando há trabalho)."""
    with app.app_context():
        if not settings_service.bot_ativado():
            sessao_ref["ativo"] = False
            return PAUSA_OCIOSA_SEGUNDOS

        telegram = collector.criar_cliente_telegram(app.config)
        if telegram is None:
            logger.warning("Bot ligado mas o Telegram não está configurado.")
            return PAUSA_OCIOSA_SEGUNDOS

        try:
            if not sessao_ref.get("ativo"):
                _descartar_pendentes(telegram)
                sessao_ref["ativo"] = True
                sessao_ref["softguard"] = _SessaoSoftGuard(app.config)

            offset = settings_service.get_bot_update_offset()
            updates = telegram.buscar_updates(
                offset=offset, timeout=TIMEOUT_POLLING_SEGUNDOS
            )
        except TelegramError as exc:
            logger.warning("Bot: falha no getUpdates (%s); tentando de novo.", exc)
            return PAUSA_ERRO_SEGUNDOS

        for update in updates:
            # O offset avança ANTES de tratar: um comando que quebre de um
            # jeito não previsto não pode ser reprocessado em loop infinito.
            settings_service.set_bot_update_offset(int(update["update_id"]) + 1)
            db.session.commit()
            try:
                processar_update(
                    update,
                    config=app.config,
                    sessao=sessao_ref["softguard"],
                    telegram=telegram,
                )
            except Exception:
                db.session.rollback()
                logger.exception("Bot: erro tratando update; o loop segue.")
    return 0


def _loop(app) -> None:
    sessao_ref: dict = {"ativo": False, "softguard": None}
    logger.info("Bot do técnico: worker iniciado.")
    while not _parar.is_set():
        try:
            espera = _uma_volta(app, sessao_ref=sessao_ref)
        except Exception:
            logger.exception("Bot: erro inesperado no loop; seguindo.")
            espera = PAUSA_ERRO_SEGUNDOS
        if espera:
            _parar.wait(espera)


def iniciar(app) -> threading.Thread:
    """Sobe o worker junto com o scheduler. A thread roda sempre e checa
    `bot_ativado` a cada volta — assim ligar/desligar na tela vale na hora,
    sem reiniciar o serviço."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return _thread
    _parar.clear()
    _thread = threading.Thread(target=_loop, args=(app,), name="telegram-bot", daemon=True)
    _thread.start()
    return _thread


def parar() -> None:
    global _thread
    _parar.set()
    _thread = None
