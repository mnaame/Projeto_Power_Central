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

from cryptography.fernet import Fernet

from app.domain.central_cliente import elegivel_automatico, gerar_identificador, montar_url
from app.domain.cofre import gerar_senha
from app.extensions import db
from app.integrations.auvo_painel_client import (
    CentralClienteCookieExpiradoError,
    CentralClientePainelClient,
    CentralClientePainelError,
    PainelCredentials,
)
from app.models.auvo import AuvoDepara
from app.models.central_cliente import CentralClienteLink, CentralClienteLote
from app.services import audit_service, settings_service

logger = logging.getLogger("central_cliente")


class CentralClienteLoteVazioError(Exception):
    """Nenhum item selecionado para o lote."""


class CentralClienteLoteEmAndamentoError(Exception):
    """Este lote já está sendo executado (clique duplo)."""


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


def _cifrar_senha(senha: str, *, config) -> str:
    chave = config["ENCRYPTION_KEY"]
    fernet = Fernet(chave.encode() if isinstance(chave, str) else chave)
    return fernet.encrypt(senha.encode()).decode()


def executar_lote(
    lote: CentralClienteLote,
    *,
    credentials: PainelCredentials | None,
    config,
    pausa_segundos: float | None = None,
    client: CentralClientePainelClient | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    user=None,
) -> CentralClienteLote:
    """Em simulação: marca todos os itens pendentes como 'criado' sem
    tocar a Auvo (guarda o que SERIA enviado). Em produção: cria contato
    por contato com pausa entre chamadas; cookie expirado aborta o
    restante do lote (itens não tentados ficam 'pendente', não 'erro').
    Falha isolada por item nunca derruba os demais."""
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
