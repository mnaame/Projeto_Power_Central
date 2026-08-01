"""BI: Eficácia do Técnico — envelopa `domain/disparos.py` (nunca reconta
BUR na mão) para responder "o atendimento reduziu os disparos do
cliente?": para cada ordem concluída na Auvo, compara disparos válidos por
dia numa janela antes × depois da conclusão.

Fica em `domain/` por ser lógica pura (sem rede/banco) — buscar as tarefas,
o histórico e persistir o resultado é responsabilidade de
`services/bi_service.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping, Sequence

from app.domain.dates import FUSO_HORARIO
from app.domain.disparos import DisparoAvaliado

JANELA_DIAS_PADRAO = 15
LIMIAR_MELHORA_PADRAO = 20.0  # % de queda no depois/dia para virar MELHOROU
LIMIAR_PIORA_PADRAO = 20.0
VISITAS_PARA_CRONICO_PADRAO = 3
AMOSTRA_MINIMA_TECNICO_PADRAO = 5

CLASSIFICACAO_MELHOROU = "MELHOROU"
CLASSIFICACAO_PIOROU = "PIOROU"
CLASSIFICACAO_ESTAVEL = "ESTAVEL"
CLASSIFICACAO_SEM_BASE = "SEM_BASE"

# taskStatus 5 = "Finalizada" — mesmo critério confirmado contra a tarefa
# real 77330829 (auvo_service.TASK_STATUS_FECHADOS); duplicado aqui como
# constante própria porque domain/ não importa de services/.
_STATUS_CONCLUIDOS = {5}

# Candidatos para a data de conclusão da tarefa — NENHUM validado contra
# produção ainda (só o booleano `checkOut` foi confirmado; o nome do campo
# de DATA de conclusão, não). `taskDate` (a data agendada, não a de
# conclusão) é o último recurso. Ver docs/BI_EFICACIA_TECNICO.md §6 — não
# confiar no ranking sem validar isto contra 1-2 tarefas reais primeiro.
_CAMPOS_DATA_CONCLUSAO = (
    "checkOutDatetime",
    "checkOutDate",
    "finishedDate",
    "modifiedDate",
    "updatedDate",
)
_CAMPO_DATA_FALLBACK = "taskDate"


def _texto(valor: object) -> str:
    return str(valor).strip() if valor is not None else ""


@dataclass(frozen=True)
class Classificacao:
    antes_por_dia: float
    depois_por_dia: float
    variacao_pct: float | None
    classificacao: str
    parcial: bool
    dias_depois: int


@dataclass(frozen=True)
class Intervencao:
    task_id_auvo: str
    conta_power: str
    id_auvo_cliente: int | None
    nome_loja: str
    tecnico_nome: str
    marco: datetime
    antes_por_dia: float
    depois_por_dia: float
    variacao_pct: float | None
    classificacao: str
    parcial: bool
    atribuicao_compartilhada: bool
    dias_depois: int


@dataclass(frozen=True)
class ResumoTecnico:
    tecnico: str
    total_intervencoes: int
    total_melhorou: int
    total_piorou: int
    total_estavel: int
    total_sem_base: int
    variacao_media_pct: float | None
    disparos_evitados: float
    amostra_pequena: bool
    antes_medio_por_dia: float
    depois_medio_por_dia: float


@dataclass(frozen=True)
class ClienteCronico:
    conta_power: str
    nome_loja: str
    total_visitas: int
    ultima_classificacao: str
    disparos_por_dia_atual: float


def tarefa_concluida(tarefa: Mapping[str, object]) -> bool:
    """Critério confirmado contra a tarefa real 77330829 (mesma régua de
    `auvo_service.TASK_STATUS_FECHADOS`)."""
    if tarefa.get("finished") is True:
        return True
    return tarefa.get("taskStatus") in _STATUS_CONCLUIDOS


def _parse_data_iso(bruto: str) -> datetime | None:
    texto = bruto.strip()
    if not texto:
        return None
    if texto.endswith("Z"):
        texto = texto[:-1] + "+00:00"
    try:
        data = datetime.fromisoformat(texto)
    except ValueError:
        return None
    if data.tzinfo is None:
        data = data.replace(tzinfo=FUSO_HORARIO)
    return data


def data_conclusao(tarefa: Mapping[str, object]) -> datetime | None:
    """Primeiro candidato que existir e parsear (ISO 8601) — ver o aviso
    de validação no topo do arquivo."""
    for campo in _CAMPOS_DATA_CONCLUSAO:
        data = _parse_data_iso(_texto(tarefa.get(campo)))
        if data is not None:
            return data
    return _parse_data_iso(_texto(tarefa.get(_CAMPO_DATA_FALLBACK)))


def classificar_janela(
    avaliados: Sequence[DisparoAvaliado],
    *,
    marco: datetime,
    agora: datetime,
    janela_dias: int = JANELA_DIAS_PADRAO,
    limiar_melhora_pct: float = LIMIAR_MELHORA_PADRAO,
    limiar_piora_pct: float = LIMIAR_PIORA_PADRAO,
) -> Classificacao:
    """Conta disparos VÁLIDOS (`d.valido`, já excluindo rotina/pânico/ciclo
    curto — `avaliados` deve vir de UMA chamada de
    `disparos.avaliar_disparos_da_conta` sobre o histórico inteiro da
    conta, nunca recortado por janela, para não perder o contexto de
    arme/desarme perto da borda) em `[marco-janela, marco)` (antes) e
    `(marco, marco+janela]` (depois), normalizados por dia. Quando o
    "depois" ainda não fechou os `janela_dias` (marco recente), usa só os
    dias já decorridos e marca `parcial=True` — nunca finge que a janela
    fechou."""
    delta = timedelta(days=janela_dias)
    antes_inicio = marco - delta
    depois_fim_alvo = marco + delta

    qtd_antes = sum(
        1
        for d in avaliados
        if d.valido and d.quando is not None and antes_inicio <= d.quando < marco
    )

    depois_fim_real = min(depois_fim_alvo, agora)
    dias_depois = max((depois_fim_real - marco).days, 0)
    parcial = depois_fim_alvo > agora

    qtd_depois = sum(
        1
        for d in avaliados
        if d.valido and d.quando is not None and marco < d.quando <= depois_fim_real
    )

    antes_por_dia = qtd_antes / janela_dias
    depois_por_dia = (qtd_depois / dias_depois) if dias_depois > 0 else 0.0

    if antes_por_dia == 0:
        return Classificacao(
            antes_por_dia=antes_por_dia,
            depois_por_dia=depois_por_dia,
            variacao_pct=None,
            classificacao=CLASSIFICACAO_SEM_BASE,
            parcial=parcial,
            dias_depois=dias_depois,
        )

    variacao_pct = (depois_por_dia - antes_por_dia) / antes_por_dia * 100
    if variacao_pct <= -limiar_melhora_pct:
        classificacao = CLASSIFICACAO_MELHOROU
    elif variacao_pct >= limiar_piora_pct:
        classificacao = CLASSIFICACAO_PIOROU
    else:
        classificacao = CLASSIFICACAO_ESTAVEL

    return Classificacao(
        antes_por_dia=antes_por_dia,
        depois_por_dia=depois_por_dia,
        variacao_pct=variacao_pct,
        classificacao=classificacao,
        parcial=parcial,
        dias_depois=dias_depois,
    )


def tem_atribuicao_compartilhada(
    marcos_da_conta: Sequence[datetime], *, marco: datetime, janela_dias: int = JANELA_DIAS_PADRAO
) -> bool:
    """True quando outra visita concluída da MESMA conta cai dentro da
    janela DEPOIS desta intervenção — não dá para creditar a queda (ou a
    falta dela) 100% a esta visita."""
    fim = marco + timedelta(days=janela_dias)
    return any(m != marco and marco < m <= fim for m in marcos_da_conta)


def resumo_por_tecnico(
    intervencoes: Sequence[Intervencao],
    *,
    amostra_minima: int = AMOSTRA_MINIMA_TECNICO_PADRAO,
) -> list[ResumoTecnico]:
    """Uma linha por técnico, ranqueada por nº de intervenções. Disparos
    evitados = soma de `(antes/dia - depois/dia) * dias_depois` — uma
    estimativa (número negativo = disparos a mais, não evitados)."""
    por_tecnico: dict[str, list[Intervencao]] = {}
    for intervencao in intervencoes:
        chave = intervencao.tecnico_nome or "(sem técnico)"
        por_tecnico.setdefault(chave, []).append(intervencao)

    resumo: list[ResumoTecnico] = []
    for tecnico, itens in por_tecnico.items():
        variacoes = [i.variacao_pct for i in itens if i.variacao_pct is not None]
        disparos_evitados = sum(
            (i.antes_por_dia - i.depois_por_dia) * i.dias_depois for i in itens
        )
        resumo.append(
            ResumoTecnico(
                tecnico=tecnico,
                total_intervencoes=len(itens),
                total_melhorou=sum(
                    1 for i in itens if i.classificacao == CLASSIFICACAO_MELHOROU
                ),
                total_piorou=sum(1 for i in itens if i.classificacao == CLASSIFICACAO_PIOROU),
                total_estavel=sum(1 for i in itens if i.classificacao == CLASSIFICACAO_ESTAVEL),
                total_sem_base=sum(
                    1 for i in itens if i.classificacao == CLASSIFICACAO_SEM_BASE
                ),
                variacao_media_pct=(sum(variacoes) / len(variacoes)) if variacoes else None,
                disparos_evitados=round(disparos_evitados, 2),
                amostra_pequena=len(itens) < amostra_minima,
                antes_medio_por_dia=round(sum(i.antes_por_dia for i in itens) / len(itens), 3),
                depois_medio_por_dia=round(sum(i.depois_por_dia for i in itens) / len(itens), 3),
            )
        )
    resumo.sort(key=lambda r: r.total_intervencoes, reverse=True)
    return resumo


def clientes_cronicos(
    intervencoes: Sequence[Intervencao],
    *,
    visitas_para_cronico: int = VISITAS_PARA_CRONICO_PADRAO,
) -> list[ClienteCronico]:
    """Contas com `visitas_para_cronico` ou mais intervenções e que AINDA
    disparam na visita mais recente — visitas repetidas sem melhora real."""
    por_conta: dict[str, list[Intervencao]] = {}
    for intervencao in intervencoes:
        if not intervencao.conta_power:
            continue
        por_conta.setdefault(intervencao.conta_power, []).append(intervencao)

    cronicos: list[ClienteCronico] = []
    for conta, itens in por_conta.items():
        if len(itens) < visitas_para_cronico:
            continue
        mais_recente = max(itens, key=lambda i: i.marco)
        if mais_recente.depois_por_dia <= 0:
            continue  # não dispara mais na visita mais recente — não é crônico
        cronicos.append(
            ClienteCronico(
                conta_power=conta,
                nome_loja=mais_recente.nome_loja,
                total_visitas=len(itens),
                ultima_classificacao=mais_recente.classificacao,
                disparos_por_dia_atual=round(mais_recente.depois_por_dia, 3),
            )
        )
    cronicos.sort(key=lambda c: c.disparos_por_dia_atual, reverse=True)
    return cronicos
