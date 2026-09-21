"""Auditoria de Horários — varre TODAS as contas da PowerCentral e separa
quais não têm horário de arme/desarme cadastrado.

O portal não tem uma tela de "contas sem horário": para saber, alguém abre
conta por conta. Este módulo faz essa varredura de uma vez, com **um
login** reaproveitado, e entrega a lista.

Sem recorte por tipo de conta: a varredura cobre a base inteira,
residência inclusive. **Falha numa conta não derruba a varredura** (mesma
disciplina do `tecnico_service.gerar_lote`) — a conta entra na contagem de
`erros` e a varredura segue, porque auditoria que morre no meio do caminho
não serve para nada.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from app.domain import horarios as dom_horarios
from app.extensions import db
from app.integrations.softguard_client import SoftGuardClient, SoftGuardError
from app.models.horarios import AuditoriaHorarioSnapshot
from app.services import audit_service, settings_service
from app.services.collector import credenciais_softguard

logger = logging.getLogger("horarios")


class AuditoriaHorariosError(Exception):
    """Não deu nem para começar a varredura (portal fora, login recusado)."""


def _criar_cliente(config) -> SoftGuardClient:
    return SoftGuardClient(credenciais_softguard(config))


def auditar(*, config, busca: str = "", softguard_client=None) -> dict:
    """Varre todas as contas e devolve
    `{"sem": [...], "com": [...], "erros": n, "total": n}`.

    `busca` recorta por número/nome — útil para reconferir um cliente sem
    varrer a base inteira de novo."""
    client = softguard_client or _criar_cliente(config)
    pausa = settings_service.get_horarios_pausa_segundos()

    try:
        linhas_contas = client.listar_todas_contas()
    except SoftGuardError as exc:
        logger.exception("Auditoria de horários: falha ao carregar as contas.")
        raise AuditoriaHorariosError(
            f"Não foi possível carregar as contas da PowerCentral: {exc}"
        ) from exc

    alvos = []
    for linha in linhas_contas:
        cue_iid = linha.get("cue_iid") or linha.get("Id")
        if cue_iid is None:
            continue  # sem id interno não há como consultar nada
        conta = dom_horarios.ContaAuditada(
            conta=str(linha.get("cue_ncuenta") or "").strip(),
            nome=str(linha.get("cue_cnombre") or "").strip(),
        )
        if dom_horarios.nome_casa(conta, busca):
            alvos.append((str(cue_iid), conta))

    sem: list[dom_horarios.ContaAuditada] = []
    com: list[dom_horarios.ContaAuditada] = []
    erros = 0

    for cue_iid, conta in alvos:
        try:
            rows = client.listar_horarios(cue_iid)
        except Exception as exc:  # noqa: BLE001 — uma conta não derruba a varredura
            logger.warning(
                "Auditoria de horários: falha na conta %s (%s): %s", conta.conta, cue_iid, exc
            )
            erros += 1
            continue

        if dom_horarios.tem_horario(rows):
            com.append(
                dom_horarios.ContaAuditada(
                    conta=conta.conta,
                    nome=conta.nome,
                    resumo=dom_horarios.resumo_horario(rows),
                )
            )
        else:
            sem.append(conta)

        if pausa:
            time.sleep(pausa)

    return {"sem": sem, "com": com, "erros": erros, "total": len(alvos)}


def _serializar(itens) -> list[dict]:
    return [{"conta": i.conta, "nome": i.nome, "resumo": i.resumo} for i in itens]


def _desserializar(linhas) -> list[dom_horarios.ContaAuditada]:
    return [
        dom_horarios.ContaAuditada(
            conta=linha.get("conta", ""),
            nome=linha.get("nome", ""),
            resumo=linha.get("resumo", ""),
        )
        for linha in (linhas or [])
    ]


def salvar_snapshot(resultado: dict) -> AuditoriaHorarioSnapshot:
    """Grava o resultado para o card do dashboard e para a tela sobreviver
    a um navegador que desistiu de esperar. Não faz commit — quem chama
    decide, junto com a auditoria."""
    snapshot = AuditoriaHorarioSnapshot(
        atualizado_em=datetime.now(timezone.utc),
        total=resultado["total"],
        sem=len(resultado["sem"]),
        com=len(resultado["com"]),
        erros=resultado["erros"],
        itens={
            "sem": _serializar(resultado["sem"]),
            "com": _serializar(resultado["com"]),
        },
    )
    db.session.add(snapshot)
    return snapshot


def ultimo_snapshot() -> AuditoriaHorarioSnapshot | None:
    return (
        AuditoriaHorarioSnapshot.query.order_by(AuditoriaHorarioSnapshot.atualizado_em.desc())
        .first()
    )


def resultado_do_snapshot(snapshot: AuditoriaHorarioSnapshot | None) -> dict | None:
    """Reconstrói o formato de `auditar` a partir do que ficou gravado."""
    if snapshot is None:
        return None
    itens = snapshot.itens or {}
    return {
        "sem": _desserializar(itens.get("sem")),
        "com": _desserializar(itens.get("com")),
        "erros": snapshot.erros,
        "total": snapshot.total,
        "atualizado_em": snapshot.atualizado_em,
    }


def registrar_auditoria(resultado: dict, *, user) -> None:
    """Auditoria da execução — só contadores, nada de nome de cliente."""
    audit_service.registrar(
        action="auditoria_horarios",
        result="success",
        user=user,
        details={
            "total": resultado["total"],
            "sem": len(resultado["sem"]),
            "com": len(resultado["com"]),
            "erros": resultado["erros"],
        },
    )
