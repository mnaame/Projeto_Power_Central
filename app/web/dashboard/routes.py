from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.domain.ordering import ordenar_por_falha_mais_antiga
from app.extensions import db
from app.models.cycle import AlertSent, CollectionCycle
from app.models.watchdog import WatchdogState
from app.services import audit_service, settings_service, tarefa_service, trigger_service

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

    tarefas_hoje = tarefa_service.contar_dia(current_user.id)

    return {
        "tarefas_hoje": tarefas_hoje,
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


@bp.route("/dashboard/atualizar", methods=["POST"])
@login_required
def atualizar():
    """Botão "Atualizar agora" (RF4) — operador e admin podem disparar."""
    try:
        cycle = trigger_service.disparar_manual(config=current_app.config, user_id=current_user.id)
        audit_service.registrar(
            action="manual_update",
            result="success" if cycle.status == "success" else "failure",
            user=current_user,
            details={"cycle_id": cycle.id, "status": cycle.status, "error": cycle.error_message},
        )
        db.session.commit()
        if cycle.status == "success":
            flash("Atualização concluída.", "info")
        else:
            flash(f"Atualização terminou com erro: {cycle.error_message}", "warning")
    except trigger_service.CicloEmAndamentoError:
        audit_service.registrar(
            action="manual_update",
            result="failure",
            user=current_user,
            details={"motivo": "ciclo_em_andamento"},
        )
        db.session.commit()
        flash("Já existe uma atualização em andamento. Aguarde terminar.", "warning")
    except trigger_service.CooldownAtivoError as exc:
        audit_service.registrar(
            action="manual_update",
            result="failure",
            user=current_user,
            details={"motivo": "cooldown", "segundos_restantes": exc.segundos_restantes},
        )
        db.session.commit()
        flash(f"Aguarde mais {exc.segundos_restantes}s antes de atualizar de novo.", "warning")

    return redirect(url_for("dashboard.index"))
