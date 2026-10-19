"""Contas em teste em lote — tela admin.

A pré-visualização fica na `session` entre o "preparar" e o "aplicar", e
o "aplicar" só aceita contas que estão nela. Remontar a lista a partir da
mensagem na hora de gravar abriria a porta para executar algo diferente
do que foi conferido — e aqui o que se grava suprime alarme.
"""

from __future__ import annotations

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required

from app.extensions import db
from app.integrations.softguard_client import SoftGuardError
from app.services import contas_teste_service, settings_service
from app.web.auth.decorators import roles_required

bp = Blueprint("contas_teste", __name__, url_prefix="/contas-teste")

CHAVE_SESSAO = "contas_teste_preview"
CONFIRMACAO = "COLOCAR EM TESTE"


def _serializar(preview: dict) -> dict:
    """Formato leve para a sessão. Guarda o essencial de cada conta —
    é esta lista, e não a mensagem, que autoriza a gravação."""
    return {
        "dias": preview["dias"],
        "inicio": preview["inicio"].strftime("%d/%m/%Y %H:%M"),
        "fim": preview["fim"].strftime("%d/%m/%Y %H:%M"),
        "casados": [
            {
                "filial": c.filial,
                "cue_iid": c.conta.cue_iid,
                "numero": c.conta.numero,
                "nome": c.conta.nome,
            }
            for c in preview["casados"]
        ],
        "ambiguos": [
            {
                "filial": c.filial,
                "candidatas": [
                    {"cue_iid": a.cue_iid, "numero": a.numero, "nome": a.nome}
                    for a in c.candidatas
                ],
            }
            for c in preview["ambiguos"]
        ],
        "nao_encontrados": [c.filial for c in preview["nao_encontrados"]],
    }


@bp.route("")
@login_required
@roles_required("admin")
def index():
    return render_template(
        "contas_teste/index.html",
        preview=session.get(CHAVE_SESSAO),
        dias_padrao=settings_service.get_teste_duracao_dias(),
        nota_padrao=settings_service.get_teste_nota_padrao(),
        confirmacao=CONFIRMACAO,
    )


@bp.route("/preparar", methods=["POST"])
@login_required
@roles_required("admin")
def preparar():
    mensagem = request.form.get("mensagem", "")
    dias = request.form.get("dias", type=int)

    try:
        preview = contas_teste_service.preparar(
            mensagem, config=current_app.config, dias=dias
        )
    except (contas_teste_service.ContasTesteError, SoftGuardError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("contas_teste.index"))

    session[CHAVE_SESSAO] = _serializar(preview)
    resumo = session[CHAVE_SESSAO]
    flash(
        f"{len(resumo['casados'])} conta(s) prontas para entrar em teste até "
        f"{resumo['fim']}. {len(resumo['nao_encontrados'])} filial(is) não "
        f"encontrada(s), {len(resumo['ambiguos'])} ambígua(s). "
        "Confira antes de aplicar — nada foi gravado ainda.",
        "info",
    )
    return redirect(url_for("contas_teste.index"))


@bp.route("/aplicar", methods=["POST"])
@login_required
@roles_required("admin")
def aplicar():
    preview = session.get(CHAVE_SESSAO)
    if not preview:
        flash("Prepare a lista antes de aplicar.", "warning")
        return redirect(url_for("contas_teste.index"))

    if (request.form.get("confirmacao") or "").strip().upper() != CONFIRMACAO:
        flash(f'Para aplicar, digite "{CONFIRMACAO}" na confirmação.', "warning")
        return redirect(url_for("contas_teste.index"))

    # Só entra o que o admin marcou, e só se estiver na pré-visualização
    # conferida: a sessão é a autorização, o formulário é o recorte dela.
    autorizados = {c["cue_iid"] for c in preview["casados"]}
    escolhidos = [i for i in request.form.getlist("cue_iid") if i in autorizados]
    if not escolhidos:
        flash("Nenhuma conta marcada.", "warning")
        return redirect(url_for("contas_teste.index"))

    try:
        resultado = contas_teste_service.aplicar(
            escolhidos,
            config=current_app.config,
            dias=preview["dias"],
            nota=request.form.get("nota") or None,
            user=current_user,
        )
    except (contas_teste_service.ContasTesteError, SoftGuardError) as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("contas_teste.index"))

    db.session.commit()
    session.pop(CHAVE_SESSAO, None)

    if resultado["falhas"]:
        flash(
            f"{len(resultado['aplicados'])} conta(s) em teste até "
            f"{resultado['fim']:%d/%m/%Y %H:%M}; "
            f"{len(resultado['falhas'])} falharam: "
            + "; ".join(f"{f['cue_iid']} ({f['erro'][:80]})" for f in resultado["falhas"]),
            "warning",
        )
    else:
        flash(
            f"{len(resultado['aplicados'])} conta(s) em teste até "
            f"{resultado['fim']:%d/%m/%Y %H:%M}. A janela expira sozinha — "
            "não há nada para desfazer depois.",
            "success",
        )
    return redirect(url_for("contas_teste.index"))
