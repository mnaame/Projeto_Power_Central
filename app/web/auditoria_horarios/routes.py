"""Auditoria de Horários — tela e export.

A varredura consulta o portal uma vez por conta, então `rodar` **grava um
snapshot e redireciona** em vez de renderizar direto: o resultado fica
guardado, a tela sobrevive a um navegador que desistiu de esperar, e um F5
não dispara a varredura de novo (padrão POST/Redirect/GET).
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

from app.extensions import db
from app.integrations.softguard_client import SoftGuardError
from app.services import audit_service, auditoria_horarios_service
from app.services.report_xlsx import gerar_xlsx_auditoria_horarios

bp = Blueprint("auditoria_horarios", __name__, url_prefix="/auditoria-horarios")


@bp.route("")
@login_required
def index():
    snapshot = auditoria_horarios_service.ultimo_snapshot()
    resultado = auditoria_horarios_service.resultado_do_snapshot(snapshot)
    return render_template("auditoria_horarios/index.html", resultado=resultado)


@bp.route("/rodar", methods=["POST"])
@login_required
def rodar():
    busca = (request.form.get("busca") or "").strip()

    try:
        resultado = auditoria_horarios_service.auditar(
            config=current_app.config, busca=busca
        )
    except (auditoria_horarios_service.AuditoriaHorariosError, SoftGuardError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("auditoria_horarios.index"))

    auditoria_horarios_service.salvar_snapshot(resultado)
    auditoria_horarios_service.registrar_auditoria(resultado, user=current_user)
    db.session.commit()

    sem = len(resultado["sem"])
    if resultado["erros"]:
        flash(
            f"Auditoria concluída: {sem} conta(s) sem horário. "
            f"{resultado['erros']} conta(s) não puderam ser consultadas.",
            "warning",
        )
    else:
        flash(f"Auditoria concluída: {sem} conta(s) sem horário.", "info")
    return redirect(url_for("auditoria_horarios.index"))


@bp.route("/exportar")
@login_required
def exportar():
    snapshot = auditoria_horarios_service.ultimo_snapshot()
    resultado = auditoria_horarios_service.resultado_do_snapshot(snapshot)
    if resultado is None:
        abort(404)

    pasta = Path(current_app.instance_path) / "reports" / "auditoria_horarios"
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    caminho = pasta / f"auditoria_horarios_{carimbo}.xlsx"

    gerar_xlsx_auditoria_horarios(
        caminho,
        sem=[(i.conta, i.nome) for i in resultado["sem"]],
        com=[(i.conta, i.nome, i.resumo) for i in resultado["com"]],
    )

    audit_service.registrar(
        action="auditoria_horarios_exportada",
        result="success",
        user=current_user,
        details={"sem": len(resultado["sem"]), "com": len(resultado["com"])},
    )
    db.session.commit()

    return send_file(caminho, as_attachment=True, download_name=caminho.name)
