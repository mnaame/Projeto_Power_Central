"""Relatório do Técnico do Dia — orquestra as três peças que já existem:
agenda da Auvo, de-para (`AuvoDepara`, reverso — id Auvo → conta) e
histórico da PowerCentral. Envelopa o motor validado do
`relatorio_tecnico.py`: mesmo cruzamento agenda↔de-para, mesmo mapa de
contas em memória, mesmo arquivo por loja (HTML nativo, extensão .xls).

Diferente dos outros relatórios (1 execução = 1 arquivo), aqui 1 lote
gera N arquivos — um por loja marcada, com falha isolada por loja (ver
`models/tecnico.py`). Só linhas `AuvoDepara` com status OK entram no
de-para reverso: REVISAR é casamento ainda não confirmado por humano, e
mostrar pro técnico o histórico da loja errada é pior do que não mostrar
nada — mesma régua de segurança já usada em `abre_chamado`.
"""

from __future__ import annotations

import logging
import threading
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Sequence

from flask import current_app

from app.domain import tecnico as dom_tecnico
from app.extensions import db
from app.integrations.softguard_client import SoftGuardClient, SoftGuardError
from app.models.auvo import AuvoDepara
from app.models.tecnico import TecnicoLote, TecnicoLoteItem
from app.services import auvo_service
from app.services.collector import credenciais_softguard

logger = logging.getLogger("tecnico")


class TecnicoAgendaError(Exception):
    """Não deu para buscar a agenda (sem credenciais da Auvo, por ex.)."""


class TecnicoLoteVazioError(Exception):
    """Nenhuma loja selecionada para o lote."""


class TecnicoLoteEmAndamentoError(Exception):
    """Este lote já está sendo gerado (segundo clique bloqueado)."""


@dataclass
class AgendaItem:
    """Uma linha da tabela de agenda cruzada com o de-para — antes de
    qualquer persistência, só para preencher a tela."""

    id_auvo_cliente: int | None
    nome_auvo: str
    conta_power: str | None
    nome_conta: str
    horario: str
    tecnico: str
    tem_depara: bool


# ----------------------------------------------------------------------
# Agenda (não persiste nada)
# ----------------------------------------------------------------------


def conta_por_id_auvo(id_auvo: int) -> AuvoDepara | None:
    """De-para reverso — só status OK (REVISAR é casamento não confirmado,
    NAO é cliente que não abre chamado; nenhum dos dois é seguro aqui).
    Duas contas podem apontar pro mesmo id_auvo (loja + tesouraria); a
    escolha é determinística (menor conta_power), não arbitrária."""
    return (
        AuvoDepara.query.filter_by(id_auvo=id_auvo, status="OK")
        .order_by(AuvoDepara.conta_power)
        .first()
    )


def buscar_agenda(
    *, config, data: date, tecnico: str, client=None
) -> list[AgendaItem]:
    """Agenda da Auvo no dia, filtrada pelo técnico e cruzada com o
    de-para reverso. Não persiste nada — alimenta só a tela."""
    auvo = client or auvo_service.criar_cliente(config)
    if auvo is None:
        raise TecnicoAgendaError("Credenciais da Auvo não configuradas.")

    data_str = data.strftime("%Y-%m-%d")
    tarefas = auvo.listar_tarefas(data_str, data_str)

    itens: list[AgendaItem] = []
    for tarefa in tarefas:
        if not dom_tecnico.tecnico_corresponde(tarefa, tecnico):
            continue
        id_cliente = dom_tecnico.id_cliente_da_tarefa(tarefa)
        linha = conta_por_id_auvo(id_cliente) if id_cliente is not None else None
        itens.append(
            AgendaItem(
                id_auvo_cliente=id_cliente,
                nome_auvo=dom_tecnico.nome_cliente_da_tarefa(tarefa),
                conta_power=linha.conta_power if linha else None,
                nome_conta=linha.nome_power if linha else "",
                horario=dom_tecnico.horario_da_tarefa(tarefa),
                tecnico=dom_tecnico.nome_tecnico_da_tarefa(tarefa),
                tem_depara=linha is not None,
            )
        )
    return itens


# ----------------------------------------------------------------------
# Lote (persiste e gera os arquivos)
# ----------------------------------------------------------------------


def criar_lote(
    *,
    selecionadas: Sequence[dict],
    data_agenda: date,
    tecnico_id_auvo: int | None,
    tecnico_nome: str,
    periodo_desde: datetime,
    periodo_hasta: datetime,
    codigos_globais: Sequence[str],
    user_id: int | None,
) -> TecnicoLote:
    """Grava o lote e um item `pendente` por loja marcada. `selecionadas`
    é uma lista de dicts com `conta_power`, `nome_loja` e, opcionalmente,
    `codigos` (override só daquela loja — sem override, herda os globais)."""
    if not selecionadas:
        raise TecnicoLoteVazioError("Nenhuma loja selecionada.")

    lote = TecnicoLote(
        criado_por_user_id=user_id,
        data_agenda=data_agenda.strftime("%Y-%m-%d"),
        tecnico_id_auvo=tecnico_id_auvo,
        tecnico_nome=tecnico_nome,
        periodo_desde=periodo_desde,
        periodo_hasta=periodo_hasta,
        codigos_globais=list(codigos_globais),
        status="running",
    )
    db.session.add(lote)
    db.session.flush()

    for loja in selecionadas:
        db.session.add(
            TecnicoLoteItem(
                lote_id=lote.id,
                conta_power=loja.get("conta_power"),
                id_auvo_cliente=loja.get("id_auvo_cliente"),
                nome_loja=loja.get("nome_loja") or "",
                horario_agenda=loja.get("horario"),
                codigos_usados=list(loja.get("codigos") or codigos_globais),
                status="pendente",
            )
        )
    db.session.flush()
    return lote


# um clique = uma execução por lote; não impede lotes diferentes em paralelo
_lock_execucao = threading.Lock()
_lotes_em_execucao: set[int] = set()


def tentar_iniciar_execucao(lote_id: int) -> bool:
    with _lock_execucao:
        if lote_id in _lotes_em_execucao:
            return False
        _lotes_em_execucao.add(lote_id)
        return True


def finalizar_execucao(lote_id: int) -> None:
    with _lock_execucao:
        _lotes_em_execucao.discard(lote_id)


def _criar_cliente_softguard(config) -> SoftGuardClient:
    return SoftGuardClient(credenciais_softguard(config))


def _pasta_lote(lote: TecnicoLote) -> Path:
    return (
        Path(current_app.instance_path)
        / "reports"
        / "tecnico"
        / lote.data_agenda
        / f"lote_{lote.id}"
    )


def gerar_lote(*, lote: TecnicoLote, config, softguard_client=None) -> TecnicoLote:
    """Para cada item pendente: resolve o `cue_iid`, baixa o histórico e
    salva o arquivo. Falha numa loja não derruba as demais — login na
    SoftGuard uma vez só, reaproveitado em todas as lojas do lote."""
    if not tentar_iniciar_execucao(lote.id):
        raise TecnicoLoteEmAndamentoError(f"O lote #{lote.id} já está sendo gerado.")

    try:
        client = softguard_client or _criar_cliente_softguard(config)

        try:
            mapa = dom_tecnico.mapa_contas(client.listar_todas_contas())
        except SoftGuardError as exc:
            logger.exception("Relatório do Técnico: falha ao carregar contas da PowerCentral.")
            lote.status = "error"
            lote.erro_mensagem = f"Falha ao carregar contas da PowerCentral: {exc}"
            for item in lote.itens:
                if item.status == "pendente":
                    item.status = "erro"
                    item.erro_mensagem = "Não foi possível carregar o mapa de contas."
            db.session.commit()
            return lote

        pasta = _pasta_lote(lote)
        pasta.mkdir(parents=True, exist_ok=True)

        gerados = erros = 0
        for item in lote.itens:
            if item.status != "pendente":
                continue

            conta = item.conta_power
            info = mapa.get(conta) if conta else None
            if info is None:
                item.status = "erro"
                item.erro_mensagem = "Conta não encontrada na PowerCentral."
                erros += 1
                db.session.flush()
                continue

            cue_iid, nome_conta = info
            nome_loja = nome_conta or item.nome_loja
            try:
                conteudo = client.exportar_historico_html(
                    cue_iid=cue_iid,
                    numero_conta=conta,
                    nome_cliente=nome_loja,
                    desde=lote.periodo_desde,
                    hasta=lote.periodo_hasta,
                    codigos_alarme=item.codigos_usados,
                )
                caminho = pasta / dom_tecnico.nome_arquivo_loja(conta, nome_loja)
                caminho.write_bytes(conteudo)
                item.arquivo_path = str(caminho)
                item.status = "gerado"
                item.gerado_em = datetime.now(timezone.utc)
                gerados += 1
            except SoftGuardError as exc:
                logger.warning(
                    "Relatório do Técnico: falha ao gerar histórico da loja %s: %s", conta, exc
                )
                item.status = "erro"
                item.erro_mensagem = str(exc)
                erros += 1
            except Exception as exc:  # uma loja não pode derrubar as demais
                logger.exception(
                    "Relatório do Técnico: erro inesperado ao gerar a loja %s.", conta
                )
                item.status = "erro"
                item.erro_mensagem = f"Erro inesperado: {exc}"
                erros += 1
            db.session.flush()

        if gerados and not erros:
            lote.status = "success"
        elif gerados:
            lote.status = "parcial"
        else:
            lote.status = "error"
        db.session.commit()
        return lote
    finally:
        finalizar_execucao(lote.id)


def montar_zip(lote: TecnicoLote) -> Path:
    """Zip só dos itens gerados com sucesso."""
    pasta = _pasta_lote(lote)
    pasta.mkdir(parents=True, exist_ok=True)
    caminho_zip = pasta / f"lote_{lote.id}.zip"
    with zipfile.ZipFile(caminho_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
        for item in lote.itens:
            if item.status != "gerado" or not item.arquivo_path:
                continue
            caminho = Path(item.arquivo_path)
            if caminho.exists():
                zipf.write(caminho, arcname=caminho.name)
    return caminho_zip
