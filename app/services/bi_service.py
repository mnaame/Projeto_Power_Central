"""BI: Eficácia do Técnico — orquestra a pergunta "o atendimento reduziu
os disparos do cliente?": busca as tarefas concluídas da Auvo no período,
busca o histórico de disparos+arme/desarme da PowerCentral numa ÚNICA
chamada (custo de rede controlado), cruza pelo de-para reverso (mesma
régua de `tecnico_service.conta_por_id_auvo`, só status OK) e aplica
`domain/bi.py`. O resultado grava em `BiRun`/`BiIntervencao` — o
dashboard só lê daqui, nunca bate na PowerCentral a cada clique.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence

from app.domain import bi as dom_bi
from app.domain import disparos as dom_disp
from app.domain import tecnico as dom_tecnico
from app.domain.dates import FUSO_HORARIO
from app.extensions import db
from app.integrations.softguard_client import SoftGuardClient
from app.models.bi import BiIntervencao, BiRun
from app.services import auvo_service, settings_service, tecnico_service
from app.services.collector import credenciais_softguard

logger = logging.getLogger("bi")

# O histórico do BI cobre todas as contas por até ~90 dias de uma vez
# (padrão bem mais pesado que os outros relatórios — Atendimentos/Disparos
# usam janelas de dias, não meses) — o timeout padrão do client (15s) não
# é suficiente para essa consulta na maioria das instalações.
TIMEOUT_HISTORICO_SEGUNDOS = 120

# Página grande (padrão do client é 100) — com todas as contas de uma
# operação real por 90 dias, 100 por página vira milhares de idas e
# voltas HTTP (cada uma com o overhead da própria chamada). "Mostrar":
# 5000 já é enviado pelo client em toda chamada de buscar_historico
# (herdado do motor validado); alinhar o tamanho da página a isso corta
# a maior parte do tempo de um recálculo grande.
PAGE_SIZE_HISTORICO = 2000

_lock_recalculo = threading.Lock()


class BiRecalculoEmAndamentoError(Exception):
    """Já existe um recálculo do BI em andamento (segundo clique bloqueado)."""


def _executar_com_lock(funcao):
    if not _lock_recalculo.acquire(blocking=False):
        raise BiRecalculoEmAndamentoError("Já existe um recálculo do BI em andamento.")
    try:
        return funcao()
    finally:
        _lock_recalculo.release()


def _criar_cliente_softguard(config) -> SoftGuardClient:
    return SoftGuardClient(credenciais_softguard(config), timeout=TIMEOUT_HISTORICO_SEGUNDOS)


def _tipo_tarefa(tarefa: Mapping[str, object]) -> int | None:
    valor = tarefa.get("taskType")
    try:
        return int(valor) if valor is not None else None
    except (TypeError, ValueError):
        return None


def _task_id(tarefa: Mapping[str, object]) -> str | None:
    for campo in ("taskID", "taskId", "id"):
        valor = tarefa.get(campo)
        if valor is not None:
            return str(valor)
    return None


def _agrupar_por_conta_power(
    eventos: Sequence[Mapping[str, object]],
) -> dict[str, list[Mapping[str, object]]]:
    """Diferente de `disparos.agrupar_por_conta` (que agrupa por
    `rec_iidcuenta`, o id interno do disparo): aqui o agrupamento precisa
    bater com `AuvoDepara.conta_power` (normalizado a partir de
    `cue_ncuenta`, mesma régua de `auvo_service.normalizar_conta`) para
    cruzar com o de-para."""
    grupos: dict[str, list[Mapping[str, object]]] = {}
    for evento in eventos:
        conta = auvo_service.normalizar_conta(evento.get("cue_ncuenta"))
        grupos.setdefault(conta, []).append(evento)
    return grupos


def _montar_resumo(
    intervencoes: Sequence[BiIntervencao], *, sem_vinculo: int, sem_data: int
) -> dict:
    disparos_evitados = sum(
        (i.antes_por_dia - i.depois_por_dia) * i.dias_depois for i in intervencoes
    )
    return {
        "total_intervencoes": len(intervencoes),
        "melhorou": sum(1 for i in intervencoes if i.classificacao == dom_bi.CLASSIFICACAO_MELHOROU),
        "piorou": sum(1 for i in intervencoes if i.classificacao == dom_bi.CLASSIFICACAO_PIOROU),
        "estavel": sum(1 for i in intervencoes if i.classificacao == dom_bi.CLASSIFICACAO_ESTAVEL),
        "sem_base": sum(1 for i in intervencoes if i.classificacao == dom_bi.CLASSIFICACAO_SEM_BASE),
        "sem_vinculo": sem_vinculo,
        "sem_data": sem_data,
        "disparos_evitados_estimados": round(disparos_evitados, 2),
    }


def recalcular(
    *,
    config,
    periodo_desde: datetime,
    periodo_hasta: datetime,
    tecnico: str = "",
    janela_dias: int | None = None,
    limiar_melhora_pct: float | None = None,
    limiar_piora_pct: float | None = None,
    user_id: int | None = None,
    auvo_client=None,
    softguard_client: SoftGuardClient | None = None,
) -> BiRun:
    """Passo pesado (RF do módulo): uma chamada de agenda + uma de
    histórico, depois tudo em memória. Falha vira `BiRun.status='error'`
    (nunca propaga — o botão "Recalcular" sempre volta para a tela).
    `janela_dias`/`limiar_*` são o ajuste "avançado" da tela — sem
    informar, cai nos padrões configurados em `settings_service`."""

    def _gerar() -> BiRun:
        janela = janela_dias if janela_dias is not None else settings_service.get_bi_janela_dias()
        limiar_melhora = (
            limiar_melhora_pct
            if limiar_melhora_pct is not None
            else settings_service.get_bi_limiar_melhora()
        )
        limiar_piora = (
            limiar_piora_pct
            if limiar_piora_pct is not None
            else settings_service.get_bi_limiar_piora()
        )
        tipos_intervencao = settings_service.get_bi_tipos_intervencao()

        run = BiRun(
            criado_por_user_id=user_id,
            periodo_desde=periodo_desde,
            periodo_hasta=periodo_hasta,
            janela_dias=janela,
            limiar_melhora_pct=limiar_melhora,
            limiar_piora_pct=limiar_piora,
            tecnico_filtro=tecnico or None,
            status="running",
        )
        db.session.add(run)
        db.session.flush()

        try:
            auvo = auvo_client or auvo_service.criar_cliente(config)
            if auvo is None:
                raise ValueError("Credenciais da Auvo não configuradas.")

            tarefas = auvo.listar_tarefas(
                periodo_desde.strftime("%Y-%m-%d"), periodo_hasta.strftime("%Y-%m-%d")
            )

            candidatas: list[tuple[Mapping[str, object], datetime, object]] = []
            sem_vinculo = 0
            sem_data = 0
            for tarefa in tarefas:
                if not dom_bi.tarefa_concluida(tarefa):
                    continue
                if not dom_tecnico.tecnico_corresponde(tarefa, tecnico):
                    continue
                if tipos_intervencao and _tipo_tarefa(tarefa) not in tipos_intervencao:
                    continue
                marco = dom_bi.data_conclusao(tarefa)
                if marco is None:
                    sem_data += 1
                    continue
                id_cliente = dom_tecnico.id_cliente_da_tarefa(tarefa)
                linha = (
                    tecnico_service.conta_por_id_auvo(id_cliente)
                    if id_cliente is not None
                    else None
                )
                if linha is None:
                    sem_vinculo += 1
                    continue
                candidatas.append((tarefa, marco, linha))

            if not candidatas:
                run.status = "success"
                run.resumo = _montar_resumo([], sem_vinculo=sem_vinculo, sem_data=sem_data)
                db.session.commit()
                return run

            agora = datetime.now(timezone.utc)
            marcos_globais = [marco for _, marco, _ in candidatas]
            folga = timedelta(minutes=6)
            desde_busca = min(marcos_globais) - timedelta(days=janela) - folga
            hasta_busca = min(max(marcos_globais) + timedelta(days=janela), agora) + folga

            client = softguard_client or _criar_cliente_softguard(config)
            codigos = (dom_disp.CODIGO_DISPARO,) + dom_disp.CODIGOS_ARME + dom_disp.CODIGOS_DESARME
            eventos = client.buscar_historico(
                codigos_alarme=codigos,
                desde=desde_busca.astimezone(FUSO_HORARIO),
                hasta=hasta_busca.astimezone(FUSO_HORARIO),
                page_size=PAGE_SIZE_HISTORICO,
            )
            eventos_por_conta = _agrupar_por_conta_power(eventos)

            marcos_por_conta: dict[str, list[datetime]] = {}
            for _, marco, linha in candidatas:
                marcos_por_conta.setdefault(linha.conta_power, []).append(marco)

            avaliados_por_conta: dict[str, list] = {}
            intervencoes: list[BiIntervencao] = []
            for tarefa, marco, linha in candidatas:
                conta = linha.conta_power
                if conta not in avaliados_por_conta:
                    avaliados_por_conta[conta] = dom_disp.avaliar_disparos_da_conta(
                        eventos_por_conta.get(conta, [])
                    )
                avaliados = avaliados_por_conta[conta]

                classificacao = dom_bi.classificar_janela(
                    avaliados,
                    marco=marco,
                    agora=agora,
                    janela_dias=janela,
                    limiar_melhora_pct=limiar_melhora,
                    limiar_piora_pct=limiar_piora,
                )
                compartilhada = dom_bi.tem_atribuicao_compartilhada(
                    marcos_por_conta[conta], marco=marco, janela_dias=janela
                )

                intervencao = BiIntervencao(
                    run_id=run.id,
                    task_id_auvo=_task_id(tarefa),
                    conta_power=conta,
                    id_auvo_cliente=linha.id_auvo,
                    nome_loja=linha.nome_power,
                    tecnico_nome=dom_tecnico.nome_tecnico_da_tarefa(tarefa),
                    marco=marco,
                    antes_por_dia=classificacao.antes_por_dia,
                    depois_por_dia=classificacao.depois_por_dia,
                    variacao_pct=classificacao.variacao_pct,
                    classificacao=classificacao.classificacao,
                    parcial=classificacao.parcial,
                    atribuicao_compartilhada=compartilhada,
                    dias_depois=classificacao.dias_depois,
                )
                db.session.add(intervencao)
                intervencoes.append(intervencao)

            db.session.flush()
            run.status = "success"
            run.resumo = _montar_resumo(intervencoes, sem_vinculo=sem_vinculo, sem_data=sem_data)
        except Exception as exc:
            logger.exception("BI: recálculo falhou.")
            run.status = "error"
            run.erro_mensagem = str(exc)

        db.session.commit()
        return run

    return _executar_com_lock(_gerar)


def ultimo_run() -> BiRun | None:
    return BiRun.query.order_by(BiRun.criado_em.desc()).first()


def carregar_run(run_id: int) -> BiRun | None:
    return db.session.get(BiRun, run_id)


def _para_intervencao_dominio(item: BiIntervencao) -> dom_bi.Intervencao:
    return dom_bi.Intervencao(
        task_id_auvo=item.task_id_auvo or "",
        conta_power=item.conta_power,
        id_auvo_cliente=item.id_auvo_cliente,
        nome_loja=item.nome_loja,
        tecnico_nome=item.tecnico_nome,
        marco=item.marco,
        antes_por_dia=item.antes_por_dia,
        depois_por_dia=item.depois_por_dia,
        variacao_pct=item.variacao_pct,
        classificacao=item.classificacao,
        parcial=item.parcial,
        atribuicao_compartilhada=item.atribuicao_compartilhada,
        dias_depois=item.dias_depois,
    )


def resumo_por_tecnico(run: BiRun) -> list[dom_bi.ResumoTecnico]:
    intervencoes = [_para_intervencao_dominio(item) for item in run.intervencoes]
    return dom_bi.resumo_por_tecnico(
        intervencoes, amostra_minima=settings_service.get_bi_amostra_minima_tecnico()
    )


def clientes_cronicos(run: BiRun) -> list[dom_bi.ClienteCronico]:
    intervencoes = [_para_intervencao_dominio(item) for item in run.intervencoes]
    return dom_bi.clientes_cronicos(
        intervencoes, visitas_para_cronico=settings_service.get_bi_visitas_para_cronico()
    )
