"""Disparos Geral (fechamento de fim de semana) — envelopa o motor
validado do `relatorio_disparos_geral.py`.

Diferente do Disparos Aleatórios (que conta só os disparos "puros" e
descarta o resto), este conta TODOS os disparos de cada cliente no
período (dedup por `rec_iid`) e CLASSIFICA cada cliente pelas categorias
de disparo presentes:

  - APÓS ARME         : disparo até 5 min DEPOIS de um arme (CLO/CLV/ROP)
  - SEGUIDO DE DESARME: disparo até 5 min ANTES de um desarme (OPN/OPV/RCL)
  - ALEATORIO         : nenhum dos dois

Um mesmo disparo pode entrar em mais de uma categoria. Acima de
`limite_recorrente` (padrão 50) a OCORRENCIA vira só "RECORRENTE".
Reaproveita a régua de janela, os códigos e o agrupamento do módulo de
Disparos Aleatórios (`domain/disparos.py`).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping, Sequence

from app.domain import disparos as dom_disp

MINUTOS_JANELA = 5  # mesma régua do Disparos Aleatórios
LIMITE_RECORRENTE_PADRAO = 50
LIMITE_TIMELINE = 8  # nº máx. de timelines consultados por cliente (eficiência)

# categorias em ordem fixa de exibição (regra §2.4 do complemento)
_ORDEM_CATEGORIAS = (
    ("arme", "APÓS ARME"),
    ("aleatorio", "ALEATORIO"),
    ("desarme", "SEGUIDO DE DESARME"),
)

GRUPO_VILLEFORT = "Villefort"
GRUPO_SUPER_NOSSO = "Super Nosso"
GRUPO_BASE = "Base"
GRUPOS = (GRUPO_VILLEFORT, GRUPO_SUPER_NOSSO, GRUPO_BASE)

PADROES_VILLEFORT_PADRAO: tuple[str, ...] = ("VILLEFORT",)
PADROES_SUPER_NOSSO_PADRAO: tuple[str, ...] = ("SUPER NOSSO", "APOIO")


@dataclass(frozen=True)
class ClienteDisparoGeral:
    conta_id: str
    conta_numero: str
    cliente: str
    quantidade: int
    ocorrencia: str
    zonas: tuple[str, ...]
    grupo: str
    ids_eventos_atendidos: tuple[str, ...]  # mais recente primeiro, p/ os tempos


def _normalizar(texto: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFD", (texto or "").upper())
        if unicodedata.category(c) != "Mn"
    )


def texto_ocorrencia(categorias: set[str], quantidade: int, limite_recorrente: int) -> str:
    """Regra §2.4/§2.5: acima do limite vira RECORRENTE; senão, junta as
    categorias presentes na ordem fixa. Uma só categoria = singular
    ("DISPARO APÓS ARME", ou só "ALEATORIO"); várias = "DISPAROS X, Y E Z"."""
    if quantidade > limite_recorrente:
        return "RECORRENTE"
    presentes = [nome for chave, nome in _ORDEM_CATEGORIAS if chave in categorias]
    if not presentes:
        return ""
    if len(presentes) == 1:
        unico = presentes[0]
        return unico if unico == "ALEATORIO" else f"DISPARO {unico}"
    return "DISPAROS " + ", ".join(presentes[:-1]) + " E " + presentes[-1]


def grupo_do_cliente(
    nome: str,
    *,
    padroes_villefort: Sequence[str] = PADROES_VILLEFORT_PADRAO,
    padroes_super_nosso: Sequence[str] = PADROES_SUPER_NOSSO_PADRAO,
) -> str:
    normalizado = _normalizar(nome)
    if any(_normalizar(p) in normalizado for p in padroes_villefort):
        return GRUPO_VILLEFORT
    if any(_normalizar(p) in normalizado for p in padroes_super_nosso):
        return GRUPO_SUPER_NOSSO
    return GRUPO_BASE


def classificar_conta(
    eventos: Sequence[Mapping[str, object]],
    *,
    limite_recorrente: int = LIMITE_RECORRENTE_PADRAO,
    janela: timedelta = timedelta(minutes=MINUTOS_JANELA),
) -> tuple[int, str, tuple[str, ...], list[Mapping[str, object]]]:
    """Devolve (quantidade, texto_ocorrencia, zonas, disparos_atendidos)
    para os eventos de UMA conta. Conta TODOS os BUR (dedup por rec_iid),
    sem excluir nenhum."""
    armes: list[datetime] = []
    desarmes: list[datetime] = []
    disparos: list[Mapping[str, object]] = []
    vistos: set[str] = set()

    for evento in eventos:
        codigo = dom_disp._codigo_evento(evento)
        if codigo in dom_disp.CODIGOS_ARME:
            quando = dom_disp._quando(evento)
            if quando is not None:
                armes.append(quando)
        elif codigo in dom_disp.CODIGOS_DESARME:
            quando = dom_disp._quando(evento)
            if quando is not None:
                desarmes.append(quando)
        elif codigo == dom_disp.CODIGO_DISPARO:
            rid = dom_disp._texto(evento.get("rec_iid"))
            if rid and rid in vistos:  # a plataforma às vezes repete o evento
                continue
            if rid:
                vistos.add(rid)
            disparos.append(evento)

    categorias: set[str] = set()
    zonas: list[str] = []
    zonas_vistas: set[str] = set()
    atendidos: list[Mapping[str, object]] = []

    for disparo in disparos:
        quando = dom_disp._quando(disparo)
        apos_arme = quando is not None and any(
            timedelta(0) <= quando - arme <= janela for arme in armes
        )
        antes_desarme = quando is not None and any(
            timedelta(0) <= desarme - quando <= janela for desarme in desarmes
        )
        if apos_arme:
            categorias.add("arme")
        if antes_desarme:
            categorias.add("desarme")
        if not apos_arme and not antes_desarme:
            categorias.add("aleatorio")

        zona = dom_disp._texto(disparo.get("_zon_cdescripcion"))
        if zona and zona not in zonas_vistas:
            zonas_vistas.add(zona)
            zonas.append(zona)

        if dom_disp._texto(disparo.get("rec_ioperador")) not in ("", "0"):
            atendidos.append(disparo)

    quantidade = len(disparos)
    ocorrencia = texto_ocorrencia(categorias, quantidade, limite_recorrente)
    return quantidade, ocorrencia, tuple(zonas), atendidos


def consolidar(
    eventos: Sequence[Mapping[str, object]],
    *,
    limite_recorrente: int = LIMITE_RECORRENTE_PADRAO,
    padroes_villefort: Sequence[str] = PADROES_VILLEFORT_PADRAO,
    padroes_super_nosso: Sequence[str] = PADROES_SUPER_NOSSO_PADRAO,
) -> list[ClienteDisparoGeral]:
    """Uma linha por cliente com pelo menos um disparo no período. Os
    eventos já vêm filtrados (BUR só do período; armes/desarmes com a
    folga de borda) — mesma disciplina do Disparos Aleatórios."""
    resultado: list[ClienteDisparoGeral] = []

    for conta_id, eventos_da_conta in dom_disp.agrupar_por_conta(eventos).items():
        quantidade, ocorrencia, zonas, atendidos = classificar_conta(
            eventos_da_conta, limite_recorrente=limite_recorrente
        )
        if quantidade == 0:
            continue

        cliente = ""
        conta_numero = ""
        for evento in eventos_da_conta:
            if not cliente:
                cliente = dom_disp._texto(evento.get("cue_cnombre"))
            if not conta_numero:
                conta_numero = dom_disp._texto(evento.get("cue_ncuenta"))
            if cliente and conta_numero:
                break

        atendidos_recentes = sorted(
            (e for e in atendidos if dom_disp._quando(e) is not None),
            key=lambda e: dom_disp._quando(e),
            reverse=True,
        )
        ids = tuple(
            dom_disp._texto(e.get("rec_iid")) for e in atendidos_recentes[:LIMITE_TIMELINE]
        )

        resultado.append(
            ClienteDisparoGeral(
                conta_id=conta_id,
                conta_numero=conta_numero,
                cliente=cliente,
                quantidade=quantidade,
                ocorrencia=ocorrencia,
                zonas=zonas,
                grupo=grupo_do_cliente(
                    cliente,
                    padroes_villefort=padroes_villefort,
                    padroes_super_nosso=padroes_super_nosso,
                ),
                ids_eventos_atendidos=ids,
            )
        )

    resultado.sort(key=lambda c: _normalizar(c.cliente))
    return resultado
