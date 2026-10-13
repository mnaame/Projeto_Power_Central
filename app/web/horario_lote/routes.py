"""Ajuste de horário em lote — telas.

Admin-only, e a execução real exige confirmação explícita. O caminho
desenhado é: preparar → baixar backup → testar em 1 conta → conferir na
plataforma → aplicar. A tela deixa esse caminho visível em vez de
oferecer um botão "fazer tudo".
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required

from app.domain import horario_lote as dom
from app.extensions import db
from app.integrations.softguard_client import SoftGuardError
from app.models.horario_lote import AjusteHorarioLote
from app.services import audit_service, horario_lote_service, settings_service
from app.services.report_xlsx import gerar_xlsx_horario_backup, gerar_xlsx_horario_lote
from app.web.auth.decorators import roles_required

bp = Blueprint("horario_lote", __name__, url_prefix="/horario-lote")

CONFIRMACAO = "APLICAR"


def _pasta() -> Path:
    return Path(current_app.instance_path) / "reports" / "horario_lote"


def _lote_ou_404(lote_id: int) -> AjusteHorarioLote:
    lote = db.session.get(AjusteHorarioLote, lote_id)
    if lote is None:
        abort(404)
    return lote


@bp.route("")
@login_required
@roles_required("admin")
def index():
    lote = horario_lote_service.ultimo_lote()
    return render_template(
        "horario_lote/index.html",
        lote=lote,
        resumo=horario_lote_service.resumo(lote) if lote else None,
        aplicar=horario_lote_service.itens(lote, categoria=dom.CATEGORIA_APLICAR) if lote else [],
        manual=horario_lote_service.itens(lote, categoria=dom.CATEGORIA_MANUAL) if lote else [],
        invalidos=horario_lote_service.itens(lote, categoria=dom.CATEGORIA_INVALIDO) if lote else [],
        simulacao=settings_service.horario_lote_simulacao(),
        delta_min=settings_service.get_horario_lote_delta_min(),
        confirmacao=CONFIRMACAO,
    )


@bp.route("/preparar", methods=["POST"])
@login_required
@roles_required("admin")
def preparar():
    try:
        lote = horario_lote_service.preparar(
            config=current_app.config, user_id=current_user.id
        )
    except (horario_lote_service.HorarioLoteError, SoftGuardError) as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("horario_lote.index"))

    audit_service.registrar(
        action="horario_lote_preparado",
        result="success",
        user=current_user,
        details={"lote_id": lote.id, "delta_min": lote.delta_min},
    )
    db.session.commit()
    flash(
        f"Lote #{lote.id} preparado em {lote.contas_varridas} conta(s). "
        "Baixe o backup antes de aplicar.",
        "info",
    )
    return redirect(url_for("horario_lote.index"))


@bp.route("/<int:lote_id>/backup")
@login_required
@roles_required("admin")
def backup(lote_id: int):
    """O desfazer. Baixar isto é pré-requisito da execução real — e o
    download fica registrado, para não restar dúvida se foi feito."""
    lote = _lote_ou_404(lote_id)
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    caminho = _pasta() / f"horario_backup_lote{lote_id}_{carimbo}.xlsx"

    gerar_xlsx_horario_backup(
        caminho,
        linhas=[
            (i.conta, i.nome, i.horario_id, i.dia_abertura, i.hora_abertura,
             i.dia_fechamento, i.antes)
            for i in horario_lote_service.itens(lote)
        ],
    )
    audit_service.registrar(
        action="horario_lote_backup",
        result="success",
        user=current_user,
        details={"lote_id": lote_id},
    )
    db.session.commit()
    return send_file(caminho, as_attachment=True, download_name=caminho.name)


@bp.route("/<int:lote_id>/exportar")
@login_required
@roles_required("admin")
def exportar(lote_id: int):
    lote = _lote_ou_404(lote_id)
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    caminho = _pasta() / f"horario_lote{lote_id}_{carimbo}.xlsx"

    def _linhas(categoria):
        return [
            (i.conta, i.nome, i.horario_id, i.dia_fechamento, i.antes, i.depois,
             i.erro_mensagem or i.status)
            for i in horario_lote_service.itens(lote, categoria=categoria)
        ]

    gerar_xlsx_horario_lote(
        caminho,
        aplicar=_linhas(dom.CATEGORIA_APLICAR),
        manual=_linhas(dom.CATEGORIA_MANUAL),
    )
    return send_file(caminho, as_attachment=True, download_name=caminho.name)


@bp.route("/<int:lote_id>/aplicar", methods=["POST"])
@login_required
@roles_required("admin")
def aplicar(lote_id: int):
    lote = _lote_ou_404(lote_id)
    apenas_conta = (request.form.get("apenas_conta") or "").strip()
    # Escrita real nesta execução, sem desarmar nada em definitivo. Uma
    # chave global desligada FICA desligada, e o próximo "aplicar" grava
    # sem que ninguém tenha decidido isso naquele momento; marcar a caixa
    # é um ato, esquecer a chave ligada não é. No lote inteiro a caixa
    # não basta — a palavra de confirmação continua obrigatória abaixo.
    gravar_de_verdade = bool(request.form.get("gravar_de_verdade"))

    # Confirmação datilografada só para o lote inteiro: o teste em uma
    # conta é justamente o passo barato que deve ser fácil de dar.
    if not apenas_conta and (request.form.get("confirmacao") or "").strip() != CONFIRMACAO:
        flash(f'Para aplicar no lote inteiro, digite "{CONFIRMACAO}" na confirmação.', "warning")
        return redirect(url_for("horario_lote.index"))

    try:
        contagem = horario_lote_service.aplicar(
            lote,
            config=current_app.config,
            user=current_user,
            apenas_conta=apenas_conta,
            gravar_de_verdade=gravar_de_verdade,
        )
    except (horario_lote_service.HorarioLoteError, SoftGuardError) as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("horario_lote.index"))

    db.session.commit()
    onde = f"na conta {apenas_conta}" if apenas_conta else "no lote inteiro"
    if lote.simulacao:
        flash(
            f"SIMULAÇÃO {onde} — nada foi gravado, e as linhas continuam "
            f"pendentes. {contagem.get('simulado', 0)} linha(s) passariam. "
            'Para gravar de verdade, marque "alterar de verdade".',
            "info",
        )
    else:
        flash(
            f"Alterado {onde}: {contagem.get('aplicado', 0)} linha(s), "
            f"{contagem.get('ja_aplicado', 0)} já estava(m) no valor novo, "
            f"{contagem.get('divergente', 0)} divergente(s), "
            f"{contagem.get('erro', 0)} com erro."
            + (" Confira na plataforma antes de soltar no lote." if apenas_conta else ""),
            "warning" if contagem.get("erro") or contagem.get("divergente") else "success",
        )
    return redirect(url_for("horario_lote.index"))
