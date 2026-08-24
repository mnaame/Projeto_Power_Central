from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import current_app

from app.domain import atendimentos as dom_atend
from app.domain import disparos as dom_disp
from app.domain import disparos_geral as dom_disp_geral
from app.domain.dates import FUSO_HORARIO, parse_softguard_datetime
from app.domain.formatting import formatar_duracao_hms
from app.extensions import db
from app.integrations.softguard_client import SoftGuardClient
from app.models.report import ReportRun
from app.services import auvo_service, settings_service
from app.services.collector import credenciais_softguard
from app.services.report_xlsx import (
    gerar_xlsx_atendimentos,
    gerar_xlsx_disparos,
    gerar_xlsx_disparos_geral,
)

logger = logging.getLogger("collector")

_locks: dict[str, threading.Lock] = {
    "atendimentos": threading.Lock(),
    "disparos": threading.Lock(),
    "disparos_geral": threading.Lock(),
}


class RelatorioEmAndamentoError(Exception):
    """Já existe uma geração deste módulo em andamento (RF de fila única)."""


def _texto(valor: object) -> str:
    return str(valor).strip() if valor is not None else ""


def _campo(evento: dict, *candidatos: str) -> str:
    for campo in candidatos:
        valor = _texto(evento.get(campo))
        if valor:
            return valor
    return ""


def _data_evento(evento: dict) -> datetime | None:
    for campo in ("rec_tfechahora", "rec_tFechaHora", "rec_tFechaHoraRecepcion", "fecha"):
        if campo in evento:
            data = parse_softguard_datetime(evento.get(campo))
            if data is not None:
                return data
    return None


def _pasta_relatorios(module: str) -> Path:
    return Path(current_app.instance_path) / "reports" / module


def _executar_com_lock(module: str, funcao):
    lock = _locks[module]
    if not lock.acquire(blocking=False):
        raise RelatorioEmAndamentoError(
            f"Já existe uma geração do relatório de {module} em andamento."
        )
    try:
        return funcao()
    finally:
        lock.release()


def _criar_cliente(config) -> SoftGuardClient:
    return SoftGuardClient(credenciais_softguard(config))


def _tempos_via_timeline(client, ids_eventos) -> tuple[str, str]:
    """Regra B.2/B.5: anda do disparo atendido mais recente para trás.
    Tempo de conclusão = primeiro evento com fechamento real (mesma
    lógica de fechamento do A.3). Tempo para ligar = primeiro evento com
    uma chamada registrada na própria linha do tempo (pode ser um disparo
    diferente do usado para a conclusão) — validado contra timeline real
    (evento MIL-0172, chamada "Atendida - Bem Sucedida")."""
    tempo_conclusao = ""
    tempo_ligar = ""
    for id_evento in ids_eventos:
        if tempo_conclusao and tempo_ligar:
            break
        analise = dom_atend.analisar_timeline(client.buscar_timeline(id_evento))
        if analise.inicio is None:
            continue
        if not tempo_conclusao and analise.fechamento is not None:
            tempo_conclusao = formatar_duracao_hms(analise.fechamento - analise.inicio)
        if not tempo_ligar and analise.chamada is not None:
            tempo_ligar = formatar_duracao_hms(analise.chamada - analise.inicio)
    return tempo_conclusao, tempo_ligar


def _formatar_horarios(horarios) -> str:
    """Um horário por linha na célula (mesmo padrão de `zonas`) — já vem
    em `FUSO_HORARIO` (`parse_softguard_datetime`); inclui a data porque
    um período manual pode passar de um dia para o outro."""
    return "\n".join(h.strftime("%d/%m %H:%M") for h in horarios)


def gerar_atendimentos(
    *,
    config,
    desde: datetime,
    hasta: datetime,
    user_id: int | None,
    softguard_client=None,
) -> ReportRun:
    """Gera o relatório de Atendimentos (módulo A) para o período."""

    def _gerar() -> ReportRun:
        run = ReportRun(
            module="atendimentos",
            generated_by_user_id=user_id,
            period_start=desde,
            period_end=hasta,
            status="running",
        )
        db.session.add(run)
        db.session.flush()

        try:
            client = softguard_client or _criar_cliente(config)
            codigos_ocorrencia = settings_service.get_atend_codigos_evento()
            # Busca também os códigos de arme (CLO/CLV/ROP — mesmos do módulo
            # de Disparos) no MESMO período: sem isso, o relatório só olha a
            # timeline da própria ocorrência e nunca sabe se a conta armou de
            # verdade depois (caso real: monitoramento fecha "não ativou" às
            # 14h sem o cliente ter armado ainda, a loja arma só às 21h — sem
            # esse cruzamento, ficava contado como falha pra sempre).
            codigos_busca = tuple(
                dict.fromkeys((*codigos_ocorrencia, *dom_disp.CODIGOS_ARME))
            )
            eventos = client.buscar_historico(
                codigos_alarme=codigos_busca,
                desde=desde.astimezone(FUSO_HORARIO),
                hasta=hasta.astimezone(FUSO_HORARIO) + timedelta(seconds=1),
            )

            codigos_ocorrencia_set = {c.upper() for c in codigos_ocorrencia}
            eventos_ocorrencia = []
            armes_por_conta: dict[str, list[datetime]] = {}
            for evento in eventos:
                codigo = _campo(evento, "rec_calarma", "cod_calarma", "codigo").upper()
                if codigo in codigos_ocorrencia_set:
                    eventos_ocorrencia.append(evento)
                if codigo in dom_disp.CODIGOS_ARME:
                    conta = _campo(evento, "cue_ncuenta", "rec_iidcuenta")
                    quando = _data_evento(evento)
                    if conta and quando is not None:
                        armes_por_conta.setdefault(conta, []).append(quando)

            incluir_automaticos = settings_service.atend_incluir_automaticos()
            incluir_abertos = settings_service.atend_incluir_abertos()
            termos_arme = settings_service.get_atend_resolucao_indica_arme()

            processados: list[dom_atend.AtendimentoProcessado] = []
            for evento in eventos_ocorrencia:
                id_evento = _campo(evento, "rec_iid")
                timeline = client.buscar_timeline(id_evento) if id_evento else []
                conta = _campo(evento, "cue_ncuenta", "rec_iidcuenta")
                processados.append(
                    dom_atend.processar_atendimento(
                        data_evento=_data_evento(evento),
                        conta=conta,
                        cliente=_campo(evento, "cue_cnombre"),
                        evento=_campo(evento, "rec_calarma", "cod_calarma", "codigo"),
                        timeline=timeline,
                        incluir_automaticos=incluir_automaticos,
                        incluir_abertos=incluir_abertos,
                        termos_arme=termos_arme,
                        armes_da_conta=armes_por_conta.get(conta, []),
                    )
                )

            incluidos = [p for p in processados if p.status == dom_atend.INCLUIDO]
            fora = [p for p in processados if p.status != dom_atend.INCLUIDO]

            def _fmt_data(d: datetime | None) -> str:
                return d.astimezone(FUSO_HORARIO).strftime("%d/%m/%Y %H:%M") if d else ""

            caminho = _pasta_relatorios("atendimentos") / (
                f"atendimentos_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.xlsx"
            )
            gerar_xlsx_atendimentos(
                caminho,
                incluidos=[
                    (
                        _fmt_data(p.data_evento),
                        p.conta,
                        p.cliente,
                        p.evento,
                        p.situacao,
                        p.tempo_atendimento,
                        p.monitor,
                    )
                    for p in incluidos
                ],
                descartados=[
                    (_fmt_data(p.data_evento), p.conta, p.cliente, p.evento, p.motivo_descarte)
                    for p in fora
                ],
            )

            run.status = "success"
            run.row_count = len(incluidos)
            run.extra_counts = {"descartados": len(fora), "total_eventos": len(processados)}
            run.file_path = str(caminho)
        except Exception as exc:
            logger.exception("Geração do relatório de atendimentos falhou.")
            run.status = "error"
            run.error_message = str(exc)

        db.session.commit()
        return run

    return _executar_com_lock("atendimentos", _gerar)


def janela_disparos(*, agora: datetime) -> tuple[datetime, datetime]:
    """Janela móvel (B.3): do fim do último relatório bem-sucedido até
    agora; primeira execução volta `disp_horas_primeira_execucao`.

    Considera só relatórios cujo period_end já passou (<= agora): um
    relatório manual sobre um período antigo não deve "resetar" o
    encadeamento para trás, mas um manual com fim no futuro (ex.: dia de
    hoje, gerado de manhã) também não pode "travar" os automáticos
    seguintes numa data que ainda não chegou."""
    ultimo = (
        ReportRun.query.filter_by(module="disparos", status="success")
        .filter(ReportRun.period_end <= agora)
        .order_by(ReportRun.period_end.desc())
        .first()
    )
    if ultimo is not None:
        return ultimo.period_end, agora
    horas = settings_service.get_disp_horas_primeira_execucao()
    return agora - timedelta(hours=horas), agora


def gerar_disparos(
    *,
    config,
    user_id: int | None,
    desde: datetime | None = None,
    hasta: datetime | None = None,
    softguard_client=None,
) -> ReportRun:
    """Gera o relatório de Disparos (módulo B). Sem `desde`/`hasta`, usa a
    janela móvel; com eles, é um override manual de período."""

    def _gerar() -> ReportRun:
        agora = datetime.now(timezone.utc)
        inicio, fim = (desde, hasta) if desde is not None and hasta is not None else (
            janela_disparos(agora=agora)
        )

        run = ReportRun(
            module="disparos",
            generated_by_user_id=user_id,
            period_start=inicio,
            period_end=fim,
            status="running",
        )
        db.session.add(run)
        db.session.flush()

        try:
            client = softguard_client or _criar_cliente(config)
            folga = timedelta(minutes=6)
            codigos = (dom_disp.CODIGO_DISPARO,) + dom_disp.CODIGOS_ARME + dom_disp.CODIGOS_DESARME
            eventos = client.buscar_historico(
                codigos_alarme=codigos,
                desde=(inicio - folga).astimezone(FUSO_HORARIO),
                hasta=(fim + folga).astimezone(FUSO_HORARIO),
            )

            na_janela = dom_disp.filtrar_para_janela(eventos, desde=inicio, hasta=fim)
            clientes = dom_disp.consolidar_clientes(
                na_janela,
                zonas_ignoradas=settings_service.get_disp_ignorar_zonas(),
                limite_recorrente=settings_service.get_disp_limite_recorrente(),
            )

            linhas = []
            for cliente in clientes:
                tempo, tempo_ligar = _tempos_via_timeline(client, cliente.ids_eventos_atendidos)
                linhas.append(
                    (
                        cliente.cliente,
                        f"{cliente.quantidade}x",
                        _formatar_horarios(cliente.horarios),
                        cliente.ocorrencia,
                        tempo,
                        tempo_ligar or "X",
                        "\n".join(cliente.zonas),
                        "",  # preenchido pelo monitor
                    )
                )

            caminho = _pasta_relatorios("disparos") / (
                f"disparos_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.xlsx"
            )
            gerar_xlsx_disparos(caminho, linhas=linhas)

            total_disparos = sum(c.quantidade for c in clientes)
            run.status = "success"
            run.row_count = len(clientes)
            run.extra_counts = {"total_disparos": total_disparos, "clientes": len(clientes)}
            run.file_path = str(caminho)

            # Gatilho Auvo (§4 do complemento de chamados): erro aqui não
            # invalida o relatório — vira registro no histórico de chamados.
            try:
                auvo_service.processar_disparos(
                    clientes, config=config, origem_user_id=user_id
                )
            except Exception:
                logger.exception(
                    "Abertura de chamados Auvo (disparos) falhou; relatório segue."
                )
        except Exception as exc:
            logger.exception("Geração do relatório de disparos falhou.")
            run.status = "error"
            run.error_message = str(exc)

        db.session.commit()
        return run

    return _executar_com_lock("disparos", _gerar)


def gerar_disparos_geral(
    *,
    config,
    desde: datetime,
    hasta: datetime,
    user_id: int | None,
    softguard_client=None,
) -> ReportRun:
    """Gera o relatório de Disparos Geral (fim de semana): conta TODOS os
    disparos por cliente, classifica por categoria, agrupa em 3 abas."""

    def _gerar() -> ReportRun:
        run = ReportRun(
            module="disparos_geral",
            generated_by_user_id=user_id,
            period_start=desde,
            period_end=hasta,
            status="running",
        )
        db.session.add(run)
        db.session.flush()

        try:
            client = softguard_client or _criar_cliente(config)
            folga = timedelta(minutes=6)
            codigos = (dom_disp.CODIGO_DISPARO,) + dom_disp.CODIGOS_ARME + dom_disp.CODIGOS_DESARME
            eventos = client.buscar_historico(
                codigos_alarme=codigos,
                desde=(desde - folga).astimezone(FUSO_HORARIO),
                hasta=(hasta + folga).astimezone(FUSO_HORARIO),
            )

            na_janela = dom_disp.filtrar_para_janela(eventos, desde=desde, hasta=hasta)
            clientes = dom_disp_geral.consolidar(
                na_janela,
                limite_recorrente=settings_service.get_dispg_limite_recorrente(),
                padroes_villefort=settings_service.get_dispg_grupo_villefort(),
                padroes_super_nosso=settings_service.get_dispg_grupo_super_nosso(),
            )

            por_grupo: dict[str, list] = {grupo: [] for grupo in dom_disp_geral.GRUPOS}
            for cliente in clientes:
                tempo, tempo_ligar = _tempos_via_timeline(client, cliente.ids_eventos_atendidos)
                por_grupo[cliente.grupo].append(
                    (
                        cliente.cliente,
                        f"{cliente.quantidade}X",
                        cliente.ocorrencia,
                        tempo,
                        tempo_ligar or "X",
                        "\n".join(cliente.zonas),
                    )
                )

            caminho = _pasta_relatorios("disparos_geral") / (
                f"disparos_geral_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.xlsx"
            )
            gerar_xlsx_disparos_geral(
                caminho, por_grupo=por_grupo, grupos=dom_disp_geral.GRUPOS
            )

            total_disparos = sum(c.quantidade for c in clientes)
            run.status = "success"
            run.row_count = len(clientes)
            run.extra_counts = {
                "total_disparos": total_disparos,
                "clientes": len(clientes),
                "por_grupo": {grupo: len(por_grupo[grupo]) for grupo in dom_disp_geral.GRUPOS},
            }
            run.file_path = str(caminho)

            # Gatilho Auvo: cliente com muitos disparos abre ordem (limite
            # próprio do Geral). Mesmo gatilho 'disparos', então a regra de
            # não reabrir enquanto a anterior está aberta vale entre os dois
            # relatórios. Erro aqui não invalida o relatório.
            try:
                auvo_service.processar_disparos(
                    clientes,
                    config=config,
                    origem_user_id=user_id,
                    minimo=settings_service.get_auvo_disp_geral_minimos_tarefa(),
                )
            except Exception:
                logger.exception(
                    "Abertura de chamados Auvo (disparos geral) falhou; relatório segue."
                )
        except Exception as exc:
            logger.exception("Geração do relatório de disparos geral falhou.")
            run.status = "error"
            run.error_message = str(exc)

        db.session.commit()
        return run

    return _executar_com_lock("disparos_geral", _gerar)
