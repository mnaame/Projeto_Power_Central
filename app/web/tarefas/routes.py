from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models.tarefa import HORIZONTES, Tarefa
from app.services import tarefa_service
from app.web.tarefas.forms import TarefaForm

bp = Blueprint("tarefas", __name__, url_prefix="/tarefas")

_ANCORA_POR_HORIZONTE = {"dia": "bloco-dia", "semana": "bloco-semana", "fixa": "bloco-fixas"}


def _carregar_ou_abort(tarefa_id: int) -> Tarefa:
    """Isolamento por dono (regra de ouro do módulo): a tarefa pode
    existir, mas se não for do usuário logado é 403 — nunca confiamos só
    no `id` da URL."""
    tarefa = db.session.get(Tarefa, tarefa_id)
    if tarefa is None:
        abort(404)
    if tarefa.user_id != current_user.id:
        abort(403)
    return tarefa


def _voltar(horizonte: str):
    return redirect(url_for("tarefas.index", _anchor=_ANCORA_POR_HORIZONTE.get(horizonte, "")))


@bp.route("")
@login_required
def index():
    hoje = tarefa_service.hoje()
    dia = tarefa_service.listar_dia(current_user.id, referencia=hoje)
    semana = tarefa_service.listar_semana(current_user.id, referencia=hoje)
    fixas = tarefa_service.listar_fixas(current_user.id)
    concluidas_hoje = tarefa_service.listar_concluidas_hoje(current_user.id, referencia=hoje)
    return render_template(
        "tarefas/index.html",
        dia=dia,
        semana=semana,
        fixas=fixas,
        concluidas_hoje=concluidas_hoje,
        hoje=hoje,
    )


@bp.route("/criar", methods=["POST"])
@login_required
def criar():
    horizonte = request.form.get("horizonte", "")
    titulo = request.form.get("titulo", "")
    if horizonte not in HORIZONTES:
        abort(400)

    try:
        tarefa_service.criar(user_id=current_user.id, titulo=titulo, horizonte=horizonte)
    except ValueError as exc:
        flash(str(exc), "warning")
        return _voltar(horizonte)

    db.session.commit()
    return _voltar(horizonte)


@bp.route("/<int:tarefa_id>/concluir", methods=["POST"])
@login_required
def concluir(tarefa_id: int):
    tarefa = _carregar_ou_abort(tarefa_id)
    horizonte = tarefa.horizonte
    tarefa_service.alternar_status(tarefa)
    db.session.commit()
    return _voltar(horizonte)


@bp.route("/<int:tarefa_id>/mover", methods=["POST"])
@login_required
def mover(tarefa_id: int):
    tarefa = _carregar_ou_abort(tarefa_id)
    novo_horizonte = request.form.get("horizonte", "")
    if novo_horizonte not in HORIZONTES:
        abort(400)
    tarefa_service.mover(tarefa, novo_horizonte=novo_horizonte)
    db.session.commit()
    return _voltar(novo_horizonte)


@bp.route("/<int:tarefa_id>/editar", methods=["GET", "POST"])
@login_required
def editar(tarefa_id: int):
    tarefa = _carregar_ou_abort(tarefa_id)
    form = TarefaForm(obj=tarefa) if request.method == "GET" else TarefaForm()

    if form.validate_on_submit():
        try:
            tarefa_service.atualizar(
                tarefa,
                titulo=form.titulo.data,
                descricao=form.descricao.data,
                horizonte=form.horizonte.data,
                data=form.data.data,
                prioridade=form.prioridade.data,
            )
        except ValueError as exc:
            flash(str(exc), "warning")
            return render_template("tarefas/form.html", form=form, tarefa=tarefa)
        db.session.commit()
        flash("Tarefa atualizada.", "info")
        return _voltar(tarefa.horizonte)

    return render_template("tarefas/form.html", form=form, tarefa=tarefa)


@bp.route("/<int:tarefa_id>/excluir", methods=["POST"])
@login_required
def excluir(tarefa_id: int):
    tarefa = _carregar_ou_abort(tarefa_id)
    horizonte = tarefa.horizonte
    tarefa_service.excluir(tarefa)
    db.session.commit()
    flash("Tarefa excluída.", "info")
    return _voltar(horizonte)
