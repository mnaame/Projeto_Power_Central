"""Minhas Tarefas — orquestração com isolamento por dono. Toda função que
opera sobre uma tarefa existente recebe o objeto já carregado; quem
garante que ele pertence ao usuário certo é a camada web
(`app/web/tarefas/routes.py`, via `_carregar_ou_abort`), nunca confiando
só no `id` da URL.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.domain.dates import FUSO_HORARIO
from app.domain.tarefas import semana_corrente
from app.extensions import db
from app.models.tarefa import PRIORIDADES, Tarefa
from app.utils.time import utcnow


def hoje() -> date:
    return datetime.now(FUSO_HORARIO).date()


def listar_dia(user_id: int, *, referencia: date | None = None) -> list[Tarefa]:
    """Tarefas do Dia de `referencia` (hoje por padrão), mais as pendentes
    de dias anteriores (atrasadas — não somem, ver `esta_atrasada`)."""
    d = referencia or hoje()
    return (
        Tarefa.query.filter(
            Tarefa.user_id == user_id,
            Tarefa.horizonte == "dia",
            db.or_(
                Tarefa.data == d,
                db.and_(Tarefa.status == "pendente", Tarefa.data < d),
            ),
        )
        .order_by(Tarefa.status.asc(), Tarefa.data.asc(), Tarefa.ordem.asc(), Tarefa.id.asc())
        .all()
    )


def listar_semana(user_id: int, *, referencia: date | None = None) -> list[Tarefa]:
    """Tarefas da Semana corrente, mais as pendentes de semanas
    anteriores (atrasadas)."""
    d = referencia or hoje()
    inicio, fim = semana_corrente(d)
    return (
        Tarefa.query.filter(
            Tarefa.user_id == user_id,
            Tarefa.horizonte == "semana",
            db.or_(
                db.and_(Tarefa.data >= inicio, Tarefa.data <= fim),
                db.and_(Tarefa.status == "pendente", Tarefa.data < inicio),
            ),
        )
        .order_by(Tarefa.status.asc(), Tarefa.data.asc(), Tarefa.ordem.asc(), Tarefa.id.asc())
        .all()
    )


def listar_fixas(user_id: int) -> list[Tarefa]:
    """Fixas pendentes — sempre visíveis, sem depender de data. As
    concluídas saem daqui (viram histórico, não somem: ver
    `listar_concluidas_hoje`/consulta direta se precisar do arquivo)."""
    return (
        Tarefa.query.filter(
            Tarefa.user_id == user_id, Tarefa.horizonte == "fixa", Tarefa.status == "pendente"
        )
        .order_by(Tarefa.ordem.asc(), Tarefa.id.asc())
        .all()
    )


def listar_concluidas_hoje(user_id: int, *, referencia: date | None = None) -> list[Tarefa]:
    """Feitas com `concluido_em` dentro do dia de `referencia` (fuso
    local) — de qualquer horizonte; a tela agrupa por bloco."""
    d = referencia or hoje()
    inicio = datetime.combine(d, datetime.min.time(), tzinfo=FUSO_HORARIO)
    fim = inicio + timedelta(days=1)
    return (
        Tarefa.query.filter(
            Tarefa.user_id == user_id,
            Tarefa.status == "feito",
            Tarefa.concluido_em >= inicio,
            Tarefa.concluido_em < fim,
        )
        .order_by(Tarefa.concluido_em.desc())
        .all()
    )


def contar_dia(user_id: int, *, referencia: date | None = None) -> dict:
    """Usado pelo cartão do dashboard: total pendente do Dia (já incluindo
    atrasadas) sem carregar as tarefas inteiras."""
    itens = listar_dia(user_id, referencia=referencia)
    pendentes = [t for t in itens if t.status == "pendente"]
    d = referencia or hoje()
    atrasadas = [t for t in pendentes if t.data is not None and t.data < d]
    return {"pendentes": len(pendentes), "atrasadas": len(atrasadas)}


def criar(*, user_id: int, titulo: str, horizonte: str, referencia: date | None = None) -> Tarefa:
    """Adição rápida: só título + horizonte. `data` é preenchida
    automaticamente (hoje pro Dia; hoje também pra Semana, já que cai
    dentro da semana corrente); Fixa fica sem data."""
    titulo_limpo = (titulo or "").strip()
    if not titulo_limpo:
        raise ValueError("Informe um título.")

    d = referencia or hoje()
    data_tarefa = d if horizonte in ("dia", "semana") else None

    tarefa = Tarefa(
        user_id=user_id, titulo=titulo_limpo, horizonte=horizonte, data=data_tarefa
    )
    db.session.add(tarefa)
    return tarefa


def atualizar(
    tarefa: Tarefa,
    *,
    titulo: str,
    descricao: str | None,
    horizonte: str,
    data: date | None,
    prioridade: str,
) -> None:
    titulo_limpo = (titulo or "").strip()
    if not titulo_limpo:
        raise ValueError("Informe um título.")
    tarefa.titulo = titulo_limpo
    tarefa.descricao = (descricao or "").strip() or None
    tarefa.horizonte = horizonte
    tarefa.data = data
    tarefa.prioridade = prioridade if prioridade in PRIORIDADES else "media"


def alternar_status(tarefa: Tarefa) -> None:
    """Checkbox: pendente -> feito (grava `concluido_em`) ou feito ->
    pendente de novo (limpa `concluido_em`, permite desmarcar)."""
    if tarefa.status == "pendente":
        tarefa.status = "feito"
        tarefa.concluido_em = utcnow()
    else:
        tarefa.status = "pendente"
        tarefa.concluido_em = None


def mover(tarefa: Tarefa, *, novo_horizonte: str, referencia: date | None = None) -> None:
    """Troca de horizonte (ex.: "→ Hoje" puxa da Semana). Ajusta `data`
    quando o novo horizonte depende dela; Fixa mantém a data como
    estava (geralmente nenhuma)."""
    d = referencia or hoje()
    tarefa.horizonte = novo_horizonte
    if novo_horizonte == "dia":
        tarefa.data = d
    elif novo_horizonte == "semana":
        inicio, fim = semana_corrente(d)
        if tarefa.data is None or not (inicio <= tarefa.data <= fim):
            tarefa.data = d


def excluir(tarefa: Tarefa) -> None:
    db.session.delete(tarefa)
