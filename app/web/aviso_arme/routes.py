"""Lojas sem arme — tela admin.

A pré-visualização fica na `session` entre o "preparar" e o "aplicar", e
o "aplicar" só aceita contas que estão nela. Remontar a lista a partir da
mensagem na hora de gravar abriria a porta para executar algo diferente
do que foi conferido — e aqui o que se grava mexe na supervisão de arme.
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
from app.services import aviso_arme_service
from app.web.auth.decorators import roles_required

bp = Blueprint("aviso_arme", __name__, url_prefix="/aviso-arme")

CHAVE_SESSAO = "aviso_arme_preview"
CONFIRMACAO = "DESLIGAR AVISO"


def _serializar(preview: dict) -> dict:
    """Formato leve para a sessão. Guarda o essencial de cada conta — é
    esta lista, e não a mensagem, que autoriza a gravação."""
    return {
        "desligar": [
            {"cue_iid": c.cue_iid, "numero": c.numero, "nome": c.nome}
            for c in preview["desligar"]
        ],
        "religar": [
            {
                "cue_iid": linha.cue_iid,
                "numero": linha.conta,
                "nome": linha.nome,
                "dias": linha.dias_desligado(),
            }
            for linha in preview["religar"]
        ],
        "ja_desligadas": [
            {"cue_iid": c.cue_iid, "numero": c.numero, "nome": c.nome}
            for c in preview["ja_desligadas"]
        ],
        "ambiguos": [
            {
                "filial": c.filial,
                "candidatas": [
                    {"numero": a.numero, "nome": a.nome} for a in c.candidatas
                ],
            }
            for c in preview["ambiguos"]
        ],
        "nao_encontrados": [c.filial for c in preview["nao_encontrados"]],
        "barradas": [
            {"numero": c.numero, "nome": c.nome} for c in preview["barradas"]
        ],
    }


@bp.route("")
@login_required
@roles_required("admin")
def index():
    return render_template(
        "aviso_arme/index.html",
        preview=session.get(CHAVE_SESSAO),
        desligadas=aviso_arme_service.desligadas_agora(),
        dias_para_alertar=aviso_arme_service.DIAS_PARA_ALERTAR,
        confirmacao=CONFIRMACAO,
    )


@bp.route("/preparar", methods=["POST"])
@login_required
@roles_required("admin")
def preparar():
    try:
        preview = aviso_arme_service.preparar(
            request.form.get("mensagem", ""), config=current_app.config
        )
    except (aviso_arme_service.AvisoArmeError, SoftGuardError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("aviso_arme.index"))

    session[CHAVE_SESSAO] = _serializar(preview)
    resumo = session[CHAVE_SESSAO]
    flash(
        f"{len(resumo['desligar'])} para desligar, "
        f"{len(resumo['religar'])} para religar. "
        f"{len(resumo['nao_encontrados'])} filial(is) não encontrada(s). "
        "Confira antes de aplicar — nada foi gravado ainda.",
        "info",
    )
    return redirect(url_for("aviso_arme.index"))


@bp.route("/aplicar", methods=["POST"])
@login_required
@roles_required("admin")
def aplicar():
    preview = session.get(CHAVE_SESSAO)
    if not preview:
        flash("Prepare a lista antes de aplicar.", "warning")
        return redirect(url_for("aviso_arme.index"))

    if (request.form.get("confirmacao") or "").strip().upper() != CONFIRMACAO:
        flash(f'Para aplicar, digite "{CONFIRMACAO}" na confirmação.', "warning")
        return redirect(url_for("aviso_arme.index"))

    # Só entra o que o admin marcou, e só se estiver na pré-visualização
    # conferida: a sessão é a autorização, o formulário é o recorte dela.
    pode_desligar = {c["cue_iid"] for c in preview["desligar"]}
    pode_religar = {c["cue_iid"] for c in preview["religar"]}
    desligar = [i for i in request.form.getlist("desligar") if i in pode_desligar]
    religar = [i for i in request.form.getlist("religar") if i in pode_religar]

    if not desligar and not religar:
        flash("Nenhuma conta marcada.", "warning")
        return redirect(url_for("aviso_arme.index"))

    try:
        resultado = aviso_arme_service.aplicar(
            desligar, religar, config=current_app.config, user=current_user
        )
    except (aviso_arme_service.AvisoArmeError, SoftGuardError) as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("aviso_arme.index"))

    db.session.commit()
    session.pop(CHAVE_SESSAO, None)

    partes = [
        f"{len(resultado['desligadas'])} desligada(s)",
        f"{len(resultado['religadas'])} religada(s)",
    ]
    if resultado["falhas"]:
        partes.append(
            f"{len(resultado['falhas'])} falha(s): "
            + "; ".join(
                f"{f['cue_iid']} ({f['erro'][:80]})" for f in resultado["falhas"]
            )
        )
    flash(
        ". ".join(partes)
        + ". O disparo continua ativo em todas — só o aviso de arme mudou.",
        "warning" if resultado["falhas"] else "success",
    )
    return redirect(url_for("aviso_arme.index"))


@bp.route("/religar-tudo", methods=["POST"])
@login_required
@roles_required("admin")
def religar_tudo():
    """Religa tudo o que está desligado, sem depender de uma lista nova.

    É a saída de emergência deste modelo: como nada expira sozinho, tem
    que existir um jeito de voltar ao normal que não dependa de o Super
    Nosso mandar a mensagem da semana."""
    linhas = aviso_arme_service.desligadas_agora()
    if not linhas:
        flash("Nenhuma conta está desligada.", "info")
        return redirect(url_for("aviso_arme.index"))

    if (request.form.get("confirmacao") or "").strip().upper() != CONFIRMACAO:
        flash(f'Para religar tudo, digite "{CONFIRMACAO}" na confirmação.', "warning")
        return redirect(url_for("aviso_arme.index"))

    try:
        resultado = aviso_arme_service.aplicar(
            [], [linha.cue_iid for linha in linhas],
            config=current_app.config, user=current_user,
        )
    except (aviso_arme_service.AvisoArmeError, SoftGuardError) as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("aviso_arme.index"))

    db.session.commit()
    session.pop(CHAVE_SESSAO, None)
    flash(
        f"{len(resultado['religadas'])} conta(s) religada(s), "
        f"{len(resultado['falhas'])} falha(s).",
        "warning" if resultado["falhas"] else "success",
    )
    return redirect(url_for("aviso_arme.index"))
