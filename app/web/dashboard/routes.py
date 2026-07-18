from __future__ import annotations

from flask import Blueprint, render_template
from flask_login import login_required

from app.domain.ordering import ordenar_por_falha_mais_antiga
from app.models.cycle import AlertSent, CollectionCycle
from app.models.watchdog import WatchdogState
from app.services import settings_service

bp = Blueprint("dashboard", __name__)

HISTORICO_LIMITE = 50
GRAFICO_LARGURA = 600
GRAFICO_ALTURA = 160
GRAFICO_MARGEM = 12


def _serie_grafico(historico: list[CollectionCycle]) -> list[dict]:
    if not historico:
        return []

    valores = [c.total_sem_comunicacao or 0 for c in historico]
    maximo = max(valores) or 1
    n = len(valores)
    passo = (GRAFICO_LARGURA - 2 * GRAFICO_MARGEM) / max(n - 1, 1)

    serie = []
    for i, cycle in enumerate(historico):
        valor = cycle.total_sem_comunicacao or 0
        x = GRAFICO_MARGEM + i * passo
        y = GRAFICO_ALTURA - GRAFICO_MARGEM - (valor / maximo) * (GRAFICO_ALTURA - 2 * GRAFICO_MARGEM)
        serie.append({"x": round(x, 1), "y": round(y, 1), "valor": valor, "quando": cycle.finished_at})
    return serie


def _dados_dashboard() -> dict:
    ultimo_sucesso = (
        CollectionCycle.query.filter_by(status="success")
        .order_by(CollectionCycle.finished_at.desc())
        .first()
    )
    ultimo_ciclo = CollectionCycle.query.order_by(CollectionCycle.started_at.desc()).first()

    contas_sem_comunicacao = []
    contas_falso_positivo = []
    if ultimo_sucesso is not None:
        contas = ultimo_sucesso.accounts.all()
        contas_sem_comunicacao = ordenar_por_falha_mais_antiga(
            [c for c in contas if c.classification == "sem_comunicacao"]
        )
        contas_falso_positivo = ordenar_por_falha_mais_antiga(
            [c for c in contas if c.classification == "falso_positivo"]
        )

    historico = list(
        reversed(
            CollectionCycle.query.filter_by(status="success")
            .order_by(CollectionCycle.finished_at.desc())
            .limit(HISTORICO_LIMITE)
            .all()
        )
    )
    serie_grafico = _serie_grafico(historico)
    pontos_grafico = " ".join(f"{p['x']},{p['y']}" for p in serie_grafico)

    return {
        "ultimo_sucesso": ultimo_sucesso,
        "ultimo_ciclo": ultimo_ciclo,
        "contas_sem_comunicacao": contas_sem_comunicacao,
        "contas_falso_positivo": contas_falso_positivo,
        "mostrar_falsos_positivos": settings_service.show_false_positives_in_panel(),
        "ultimo_alerta": AlertSent.query.order_by(AlertSent.sent_at.desc()).first(),
        "watchdog": WatchdogState.query.first(),
        "serie_grafico": serie_grafico,
        "pontos_grafico": pontos_grafico,
        "grafico_largura": GRAFICO_LARGURA,
        "grafico_altura": GRAFICO_ALTURA,
    }


@bp.route("/")
@login_required
def index():
    return render_template("dashboard/index.html", **_dados_dashboard())


@bp.route("/dashboard/painel")
@login_required
def painel_parcial():
    """Fragmento HTML recarregado por polling (RF2) — mesma renderização
    usada dentro da página completa."""
    return render_template("dashboard/_conteudo.html", **_dados_dashboard())
