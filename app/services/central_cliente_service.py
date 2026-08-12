"""Links da Central do Cliente (Auvo) — orquestração. Módulo de maior
risco do sistema: cria contatos reais na Auvo com link de acesso sem
login/senha. Simulação por padrão, admin-only (checado na rota), cookie
de sessão nunca persiste (parâmetro de função, descartado ao fim da
execução). Ver docs/CENTRAL_CLIENTE.md para o desenho completo.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Iterable

from cryptography.fernet import Fernet, InvalidToken

from app.domain.central_cliente import (
    elegivel_automatico,
    gerar_identificador,
    montar_link_whatsapp,
    montar_url,
    normalizar_telefone,
)
from app.domain.cofre import gerar_senha
from app.extensions import db
from app.integrations.auvo_client import AuvoClient, AuvoError
from app.integrations.auvo_painel_client import (
    CentralClienteCookieExpiradoError,
    CentralClientePainelClient,
    CentralClientePainelError,
    PainelCredentials,
)
from app.models.auvo import AuvoDepara
from app.models.central_cliente import CentralClienteLink, CentralClienteLote
from app.services import audit_service, auvo_service, settings_service

logger = logging.getLogger("central_cliente")


class CentralClienteLoteVazioError(Exception):
    """Nenhum item selecionado para o lote."""


class CentralClienteLoteEmAndamentoError(Exception):
    """Este lote já está sendo executado (clique duplo)."""


class CentralClienteLinkNaoRemovivelError(Exception):
    """Só dá pra remover um registro com status 'criado' — pendente/erro
    não bloqueiam ninguém, e 'removido' já está removido."""


# ----------------------------------------------------------------------
# Montagem do lote (elegibilidade + dedup) e pré-visualização
# ----------------------------------------------------------------------


def montar_lote(*, score_minimo: float | None = None, ids_extra: Iterable[int] = ()) -> list[dict]:
    """Candidatos elegíveis: de-para OK com score >= mínimo (automático),
    ou marcados manualmente em `ids_extra` (REVISAR/NAO/score baixo — só
    entram com marcação humana, por especificação). Exclui quem já tem
    link `criado` **num lote real** (idempotência por `id_auvo`, não por
    conta — duas contas do mesmo cliente Auvo geram só um candidato).
    Um `criado` de lote em simulação não conta — simular não deveria ter
    efeito nenhum sobre o que ainda pode ser rodado de verdade."""
    if score_minimo is None:
        score_minimo = settings_service.get_central_score_minimo()
    ids_extra_set = {int(i) for i in ids_extra}

    ja_criados = {
        linha.id_auvo
        for linha in CentralClienteLink.query.join(CentralClienteLote)
        .filter(CentralClienteLink.status == "criado", CentralClienteLote.simulacao.is_(False))
        .all()
    }

    candidatos: dict[int, dict] = {}
    for linha in AuvoDepara.query.order_by(AuvoDepara.conta_power).all():
        if linha.id_auvo is None or linha.id_auvo in ja_criados or linha.id_auvo in candidatos:
            continue
        elegivel = elegivel_automatico(linha.status, linha.score, score_minimo=score_minimo)
        if not (elegivel or linha.id_auvo in ids_extra_set):
            continue
        candidatos[linha.id_auvo] = {
            "id_auvo": linha.id_auvo,
            "nome": linha.nome_auvo or linha.nome_power,
            "conta_power": linha.conta_power,
            "status_depara": linha.status,
            "score": linha.score,
            "manual": not elegivel,
        }
    return list(candidatos.values())


def buscar_clientes(termo: str, *, limite: int = 30) -> list[dict]:
    """Lookup por nome (Power ou Auvo), conta ou id_auvo — diferente de
    `montar_lote`, aqui NÃO filtra por elegibilidade nem exclui quem já
    tem link: o objetivo é achar um cliente específico e mostrar o
    estado real dele (inclusive "já tem link"), não montar um lote novo.
    Sem isso, um cliente que já recebeu link simplesmente some de
    qualquer busca — parece que nunca existiu, quando na verdade já foi
    processado."""
    termo = (termo or "").strip()
    if not termo:
        return []

    query = AuvoDepara.query
    if termo.isdigit():
        query = query.filter(
            db.or_(AuvoDepara.id_auvo == int(termo), AuvoDepara.conta_power == termo)
        )
    else:
        padrao = f"%{termo}%"
        query = query.filter(
            db.or_(AuvoDepara.nome_power.ilike(padrao), AuvoDepara.nome_auvo.ilike(padrao))
        )
    linhas = query.order_by(AuvoDepara.conta_power).limit(limite).all()

    resultados: list[dict] = []
    vistos: set[int] = set()
    for linha in linhas:
        if linha.id_auvo is None or linha.id_auvo in vistos:
            continue
        vistos.add(linha.id_auvo)

        link_existente = (
            CentralClienteLink.query.join(CentralClienteLote)
            .filter(CentralClienteLink.id_auvo == linha.id_auvo, CentralClienteLink.status == "criado")
            .order_by(CentralClienteLink.criado_em.desc())
            .first()
        )
        resultados.append(
            {
                "id_auvo": linha.id_auvo,
                "nome": linha.nome_auvo or linha.nome_power,
                "conta_power": linha.conta_power,
                "status_depara": linha.status,
                "score": linha.score,
                "link_existente": link_existente,
            }
        )
    return resultados


def prever(candidatos: list[dict]) -> list[dict]:
    """Pré-visualização (§1 passo 3): nada é persistido nem enviado à
    Auvo. O identificador mostrado é só ilustrativo — um novo é gerado na
    hora de executar, para não exibir um link que nunca chega a existir
    se o item for desmarcado antes da confirmação."""
    menus = {
        "solicitacoes": settings_service.central_menu_solicitacoes(),
        "os": settings_service.central_menu_os(),
        "orcamento": settings_service.central_menu_orcamento(),
    }
    previa = []
    for candidato in candidatos:
        identificador = gerar_identificador()
        previa.append(
            {
                **candidato,
                "link_identificador": identificador,
                "link_url": montar_url(identificador),
                "menus": menus,
                "gerar_login_senha": settings_service.central_gerar_login_senha(),
            }
        )
    return previa


# ----------------------------------------------------------------------
# Criação do lote (persiste "pendente" imediatamente — sobrevive mesmo
# que a execução falhe logo depois, mesmo motivo do BI/Técnico)
# ----------------------------------------------------------------------


def criar_lote(
    itens_selecionados: list[dict], *, simulacao: bool, user_id: int | None
) -> CentralClienteLote:
    if not itens_selecionados:
        raise CentralClienteLoteVazioError()

    lote = CentralClienteLote(
        simulacao=simulacao,
        status="running",
        total_itens=len(itens_selecionados),
        criado_por_user_id=user_id,
    )
    db.session.add(lote)
    db.session.flush()
    for item in itens_selecionados:
        db.session.add(
            CentralClienteLink(
                lote_id=lote.id,
                id_auvo=int(item["id_auvo"]),
                nome=str(item.get("nome") or ""),
                status="pendente",
            )
        )
    db.session.commit()
    return lote


# um clique = uma execução por lote; não impede lotes diferentes em paralelo
_lock_execucao = threading.Lock()
_lotes_em_execucao: set[int] = set()


def _tentar_iniciar(lote_id: int) -> bool:
    with _lock_execucao:
        if lote_id in _lotes_em_execucao:
            return False
        _lotes_em_execucao.add(lote_id)
        return True


def _finalizar(lote_id: int) -> None:
    with _lock_execucao:
        _lotes_em_execucao.discard(lote_id)


def _fernet(config) -> Fernet:
    chave = config["ENCRYPTION_KEY"]
    return Fernet(chave.encode() if isinstance(chave, str) else chave)


def _cifrar_senha(senha: str, *, config) -> str:
    return _fernet(config).encrypt(senha.encode()).decode()


def _decifrar_senha(senha_cifrada: str, *, config) -> str:
    return _fernet(config).decrypt(senha_cifrada.encode()).decode()


# ----------------------------------------------------------------------
# Telefone (API oficial) e WhatsApp assistido (§5.5)
# ----------------------------------------------------------------------


def _id_cliente_auvo(cliente: dict) -> int | None:
    for chave in ("id", "customerId", "idCustomer"):
        valor = cliente.get(chave)
        if valor is not None:
            try:
                return int(valor)
            except (TypeError, ValueError):
                continue
    return None


def _telefones_brutos_cliente(cliente: dict) -> list[str]:
    """`phoneNumber` na API oficial vem como **lista** (mesmo com um único
    telefone, ex.: `["31999998888"]`) — confirmado em produção (cliente com
    2 números). Devolve todos os telefones não vazios do primeiro campo
    preenchido (se vier como texto solto, formato alternativo, devolve
    numa lista de 1)."""
    for chave in ("phoneNumber", "phone", "cellPhone"):
        valor = cliente.get(chave)
        if isinstance(valor, (list, tuple)):
            numeros = [str(item or "").strip() for item in valor if str(item or "").strip()]
            if numeros:
                return numeros
            continue
        texto = str(valor or "").strip()
        if texto:
            return [texto]
    return []


def _mapa_telefones(client: AuvoClient) -> dict[int, list[str]]:
    """id_auvo -> lista de telefones brutos (ainda não normalizados),
    best-effort a partir da API oficial. Nunca levanta — uma falha aqui
    não pode derrubar a criação dos contatos, só deixa telefone/WhatsApp
    de fora para aquele lote."""
    try:
        clientes = client.listar_clientes()
    except AuvoError:
        logger.warning("Central do Cliente: falha ao buscar telefones na Auvo (API oficial).")
        return {}
    mapa: dict[int, list[str]] = {}
    for cliente in clientes:
        cid = _id_cliente_auvo(cliente)
        telefones = _telefones_brutos_cliente(cliente)
        if cid is not None and telefones:
            mapa[cid] = telefones
    return mapa


class _ContextoMensagem(dict):
    """Placeholder desconhecido no template fica literal em vez de
    KeyError — o template é editável pelo admin e não pode derrubar a
    tela."""

    def __missing__(self, chave: str) -> str:
        return "{" + chave + "}"


def renderizar_mensagem_whatsapp(*, nome: str, link: str, login: str = "", senha: str = "") -> str:
    template = settings_service.get_central_whatsapp_template()
    contexto = _ContextoMensagem(nome=nome, link=link, login=login, senha=senha)
    return template.format_map(contexto)


def montar_link_whatsapp_item(item: CentralClienteLink, *, telefone: str, config) -> str | None:
    """Link `wa.me` pronto pro item, com a mensagem preenchida — ou
    `None` se `telefone` não for um dos telefones válidos do item (a tela
    só deve oferecer os números que vieram da Auvo pra aquele cliente,
    nunca um número arbitrário). Envio continua assistido: só monta o
    link, quem confirma o envio é o humano clicando dentro do WhatsApp."""
    if not item.telefones or telefone not in item.telefones:
        return None
    senha = ""
    if item.senha_cifrada:
        try:
            senha = _decifrar_senha(item.senha_cifrada, config=config)
        except InvalidToken:
            senha = ""
    mensagem = renderizar_mensagem_whatsapp(
        nome=item.nome, link=item.link_url or "", login=item.login or "", senha=senha
    )
    return montar_link_whatsapp(telefone, mensagem)


def executar_lote(
    lote: CentralClienteLote,
    *,
    credentials: PainelCredentials | None,
    config,
    pausa_segundos: float | None = None,
    client: CentralClientePainelClient | None = None,
    auvo_client: AuvoClient | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    user=None,
) -> CentralClienteLote:
    """Em simulação: marca todos os itens pendentes como 'criado' sem
    tocar a Auvo (guarda o que SERIA enviado). Em produção: cria contato
    por contato com pausa entre chamadas; cookie expirado aborta o
    restante do lote (itens não tentados ficam 'pendente', não 'erro').
    Falha isolada por item nunca derruba os demais. Telefone é buscado na
    API OFICIAL (não no endpoint interno) e normalizado — falha nessa
    busca não derruba o lote, só deixa o WhatsApp indisponível."""
    if not _tentar_iniciar(lote.id):
        raise CentralClienteLoteEmAndamentoError(f"O lote #{lote.id} já está sendo executado.")

    try:
        if pausa_segundos is None:
            pausa_segundos = settings_service.get_central_pausa_segundos()
        cargo = settings_service.get_central_cargo_padrao()
        gerar_login_senha = settings_service.central_gerar_login_senha()
        menu_solicitacoes = settings_service.central_menu_solicitacoes()
        menu_os = settings_service.central_menu_os()
        menu_orcamento = settings_service.central_menu_orcamento()
        ddi_whatsapp = settings_service.get_central_whatsapp_ddi()

        cliente_oficial = auvo_client if auvo_client is not None else auvo_service.criar_cliente(config)
        mapa_telefones = _mapa_telefones(cliente_oficial) if cliente_oficial is not None else {}

        pendentes = [item for item in lote.itens if item.status == "pendente"]

        if not lote.simulacao and credentials is None:
            for item in pendentes:
                item.status = "erro"
                item.erro_mensagem = "Cookie/auvo-user-request não informados."
            lote.status = "error"
            lote.total_falha = len(pendentes)
            db.session.commit()
            return lote

        painel = None
        if not lote.simulacao:
            painel = client or CentralClientePainelClient(credentials)

        sucesso = falha = 0
        abortado_por_cookie = False

        for item in pendentes:
            identificador = gerar_identificador()
            link_url = montar_url(identificador)
            login = f"cliente{item.id_auvo}" if gerar_login_senha else ""
            senha_plana = gerar_senha() if gerar_login_senha else ""
            menus = {
                "solicitacoes": menu_solicitacoes,
                "os": menu_os,
                "orcamento": menu_orcamento,
            }
            telefones_brutos = mapa_telefones.get(item.id_auvo, [])
            telefones_normalizados: list[str] = []
            for bruto in telefones_brutos:
                normalizado = normalizar_telefone(bruto, ddi=ddi_whatsapp)
                if normalizado and normalizado not in telefones_normalizados:
                    telefones_normalizados.append(normalizado)
            item.telefones = telefones_normalizados or None

            if lote.simulacao:
                item.link_identificador = identificador
                item.link_url = link_url
                item.login = login or None
                item.senha_cifrada = _cifrar_senha(senha_plana, config=config) if senha_plana else None
                item.menus = menus
                item.status = "criado"
                sucesso += 1
                db.session.flush()
                continue

            try:
                contato_codigo = painel.criar_contato_link(
                    nome=item.nome,
                    cargo=cargo,
                    login=login,
                    senha=senha_plana,
                    link_acesso=identificador,
                    habilita_menu_solicitacoes=menu_solicitacoes,
                    habilita_menu_os=menu_os,
                    habilita_menu_orcamento=menu_orcamento,
                    codigo_cliente=item.id_auvo,
                )
            except CentralClienteCookieExpiradoError as exc:
                logger.warning("Central do Cliente: cookie expirado, abortando lote #%s.", lote.id)
                lote.erro_mensagem = str(exc)
                abortado_por_cookie = True
                db.session.flush()
                break
            except CentralClientePainelError as exc:
                logger.warning(
                    "Central do Cliente: falha ao criar contato para id_auvo=%s: %s",
                    item.id_auvo,
                    exc,
                )
                item.status = "erro"
                item.erro_mensagem = str(exc)
                falha += 1
                db.session.flush()
                continue
            except Exception as exc:  # um cliente não pode derrubar o lote
                logger.exception(
                    "Central do Cliente: erro inesperado ao criar contato para id_auvo=%s.",
                    item.id_auvo,
                )
                item.status = "erro"
                item.erro_mensagem = f"Erro inesperado: {exc}"
                falha += 1
                db.session.flush()
                continue

            item.contato_codigo = contato_codigo
            item.link_identificador = identificador
            item.link_url = link_url
            item.login = login or None
            item.senha_cifrada = _cifrar_senha(senha_plana, config=config) if senha_plana else None
            item.menus = menus
            item.status = "criado"
            sucesso += 1
            audit_service.registrar(
                action="central_link_criado",
                result="success",
                user=user,
                details={
                    "lote_id": lote.id,
                    "id_auvo": item.id_auvo,
                    "nome": item.nome,
                    "contato_codigo": contato_codigo,
                },
            )
            db.session.flush()
            sleep_fn(pausa_segundos)

        lote.total_sucesso = sucesso
        lote.total_falha = falha
        if abortado_por_cookie:
            lote.status = "parcial" if sucesso else "error"
        elif sucesso and not falha:
            lote.status = "success"
        elif sucesso:
            lote.status = "parcial"
        else:
            lote.status = "error"
        db.session.commit()
        return lote
    finally:
        _finalizar(lote.id)


def remover_link(item: CentralClienteLink, *, user=None) -> None:
    """Marca o registro como 'removido' — usar quando o contato foi
    apagado manualmente na Auvo (ex.: era um teste). Não apaga a linha
    (mantém o histórico de auditoria); só libera o cliente pra aparecer
    como candidato de novo, já que `montar_lote` só exclui
    `status == 'criado'`. Não faz nenhuma chamada à Auvo — quem já apagou
    o contato lá é o admin, isto só sincroniza o nosso lado."""
    if item.status != "criado":
        raise CentralClienteLinkNaoRemovivelError(
            f"Só é possível remover um item com status 'criado' (atual: {item.status})."
        )
    item.status = "removido"
    audit_service.registrar(
        action="central_link_removido",
        result="success",
        user=user,
        details={"lote_id": item.lote_id, "id_auvo": item.id_auvo, "nome": item.nome},
    )
