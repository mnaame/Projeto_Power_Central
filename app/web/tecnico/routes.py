from __future__ import annotations

from datetime import date, datetime, time, timedelta
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

from app.domain.dates import FUSO_HORARIO
from app.extensions import db
from app.integrations.auvo_client import AuvoError
from app.models.tecnico import TecnicoLote, TecnicoLoteItem
from app.services import audit_service, settings_service, tecnico_service
from app.web.auth.decorators import roles_required
from app.web.tecnico.forms import ConfiguracaoTecnicoForm

bp = Blueprint("tecnico", __name__, url_prefix="/tecnico")

LOTES_HISTORICO_LIMITE = 20


def _parse_codigos(bruto: str | None) -> list[str]:
    if not bruto:
        return []
    return [codigo.strip().upper() for codigo in bruto.split(",") if codigo.strip()]


def _parse_data_agenda(bruto: str | None) -> date:
    bruto = (bruto or "").strip()
    if not bruto:
        return datetime.now(FUSO_HORARIO).date()
    return datetime.strptime(bruto, "%Y-%m-%d").date()


def _periodo_historico(data_agenda: date) -> tuple[datetime, datetime]:
    """Preset "últimos N dias" (padrão configurável) ou período manual com
    hora — manual vence quando os dois campos vierem preenchidos. Mesma
    régua do motor validado: início 00:00 do dia (menos N dias), fim
    23:59:59 do dia da agenda."""
    inicio_manual = (request.form.get("periodo_inicio") or "").strip()
    fim_manual = (request.form.get("periodo_fim") or "").strip()
    if inicio_manual and fim_manual:
        desde = datetime.strptime(inicio_manual, "%Y-%m-%dT%H:%M").replace(tzinfo=FUSO_HORARIO)
        hasta = datetime.strptime(fim_manual, "%Y-%m-%dT%H:%M").replace(tzinfo=FUSO_HORARIO)
    else:
        dias = request.form.get("dias_historico", type=int) or settings_service.get_tecnico_periodo_dias_padrao()
        desde = datetime.combine(data_agenda, time.min, tzinfo=FUSO_HORARIO) - timedelta(days=dias)
        hasta = datetime.combine(data_agenda, time(23, 59, 59), tzinfo=FUSO_HORARIO)
    if hasta < desde:
        raise ValueError("Período inválido: fim antes do início.")
    return desde, hasta


def _filtros_padrao() -> dict:
    return {
        "data_agenda": datetime.now(FUSO_HORARIO).strftime("%Y-%m-%d"),
        "tecnico": settings_service.get_tecnico_nome_padrao(),
        "dias_historico": settings_service.get_tecnico_periodo_dias_padrao(),
        "periodo_inicio": "",
        "periodo_fim": "",
        "codigos": ",".join(settings_service.get_tecnico_codigos_padrao()),
    }


def _filtros_do_form(data_agenda: date, tecnico: str, codigos: list[str]) -> dict:
    return {
        "data_agenda": data_agenda.strftime("%Y-%m-%d"),
        "tecnico": tecnico,
        "dias_historico": request.form.get("dias_historico")
        or settings_service.get_tecnico_periodo_dias_padrao(),
        "periodo_inicio": request.form.get("periodo_inicio") or "",
        "periodo_fim": request.form.get("periodo_fim") or "",
        "codigos": ",".join(codigos),
    }


def _lotes_recentes() -> list[TecnicoLote]:
    return (
        TecnicoLote.query.order_by(TecnicoLote.criado_em.desc())
        .limit(LOTES_HISTORICO_LIMITE)
        .all()
    )


@bp.route("")
@login_required
def index():
    return render_template(
        "tecnico/index.html", filtros=_filtros_padrao(), agenda=None, lotes=_lotes_recentes()
    )


@bp.route("/agenda", methods=["POST"])
@login_required
def puxar_agenda():
    try:
        data_agenda = _parse_data_agenda(request.form.get("data_agenda"))
    except ValueError:
        flash("Data da agenda inválida.", "warning")
        return redirect(url_for("tecnico.index"))

    tecnico = (request.form.get("tecnico") or "").strip()
    codigos = _parse_codigos(request.form.get("codigos")) or list(
        settings_service.get_tecnico_codigos_padrao()
    )
    filtros = _filtros_do_form(data_agenda, tecnico, codigos)

    periodo = None
    try:
        periodo = _periodo_historico(data_agenda)
    except ValueError:
        flash("Período do histórico inválido — confira as datas.", "warning")

    try:
        agenda = tecnico_service.buscar_agenda(
            config=current_app.config, data=data_agenda, tecnico=tecnico
        )
    except tecnico_service.TecnicoAgendaError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("tecnico.index"))
    except AuvoError as exc:
        flash(f"Erro ao consultar a agenda da Auvo: {exc}", "error")
        return redirect(url_for("tecnico.index"))

    return render_template(
        "tecnico/index.html",
        filtros=filtros,
        agenda=agenda,
        periodo=periodo,
        lotes=_lotes_recentes(),
    )


@bp.route("/gerar", methods=["POST"])
@login_required
def gerar():
    try:
        data_agenda = _parse_data_agenda(request.form.get("data_agenda"))
    except ValueError:
        flash("Data da agenda inválida.", "warning")
        return redirect(url_for("tecnico.index"))

    tecnico = (request.form.get("tecnico") or "").strip()
    codigos_globais = _parse_codigos(request.form.get("codigos")) or list(
        settings_service.get_tecnico_codigos_padrao()
    )

    try:
        periodo_desde, periodo_hasta = _periodo_historico(data_agenda)
    except ValueError:
        flash("Período do histórico inválido — confira as datas.", "warning")
        return redirect(url_for("tecnico.index"))

    total = request.form.get("total_linhas", type=int) or 0
    selecionadas_idx = set()
    for bruto in request.form.getlist("selecionar"):
        try:
            selecionadas_idx.add(int(bruto))
        except ValueError:
            continue

    selecionadas = []
    for i in range(total):
        if i not in selecionadas_idx:
            continue
        conta = (request.form.get(f"conta_power_{i}") or "").strip() or None
        nome_loja = (request.form.get(f"nome_loja_{i}") or "").strip()
        id_cliente_bruto = (request.form.get(f"id_auvo_cliente_{i}") or "").strip()
        horario = (request.form.get(f"horario_{i}") or "").strip()
        codigos_linha = _parse_codigos(request.form.get(f"codigos_{i}")) or codigos_globais
        selecionadas.append(
            {
                "conta_power": conta,
                "nome_loja": nome_loja,
                "id_auvo_cliente": int(id_cliente_bruto) if id_cliente_bruto.isdigit() else None,
                "horario": horario,
                "codigos": codigos_linha,
            }
        )

    tecnico_id = int(tecnico) if tecnico.isdigit() else None

    try:
        lote = tecnico_service.criar_lote(
            selecionadas=selecionadas,
            data_agenda=data_agenda,
            tecnico_id_auvo=tecnico_id,
            tecnico_nome=tecnico,
            periodo_desde=periodo_desde,
            periodo_hasta=periodo_hasta,
            codigos_globais=codigos_globais,
            user_id=current_user.id,
        )
    except tecnico_service.TecnicoLoteVazioError:
        flash("Selecione ao menos uma loja para gerar.", "warning")
        return redirect(url_for("tecnico.index"))
    db.session.commit()  # mantém o lote (com itens "pendente") mesmo se a geração falhar logo em seguida

    try:
        lote = tecnico_service.gerar_lote(lote=lote, config=current_app.config)
    except tecnico_service.TecnicoLoteEmAndamentoError:
        flash("Este lote já está sendo gerado.", "warning")
        return redirect(url_for("tecnico.lote_detalhe", lote_id=lote.id))

    gerados = sum(1 for item in lote.itens if item.status == "gerado")
    erros = sum(1 for item in lote.itens if item.status == "erro")
    audit_service.registrar(
        action="tecnico_lote_gerado",
        result="success" if lote.status in ("success", "parcial") else "failure",
        user=current_user,
        details={
            "lote_id": lote.id,
            "data_agenda": lote.data_agenda,
            "tecnico": lote.tecnico_nome,
            "gerados": gerados,
            "erros": erros,
        },
    )
    db.session.commit()

    if lote.status == "success":
        flash(f"Relatório gerado: {gerados} loja(s).", "info")
    elif lote.status == "parcial":
        flash(f"Relatório gerado com falhas: {gerados} ok, {erros} com erro.", "warning")
    else:
        flash("Falha ao gerar o relatório — nenhuma loja foi gerada.", "error")
    return redirect(url_for("tecnico.lote_detalhe", lote_id=lote.id))


@bp.route("/lote/<int:lote_id>")
@login_required
def lote_detalhe(lote_id: int):
    lote = db.session.get(TecnicoLote, lote_id)
    if lote is None:
        abort(404)
    gerados = sum(1 for item in lote.itens if item.status == "gerado")
    erros = sum(1 for item in lote.itens if item.status == "erro")
    return render_template("tecnico/lote.html", lote=lote, gerados=gerados, erros=erros)


@bp.route("/lote/<int:lote_id>/item/<int:item_id>/download")
@login_required
def download_item(lote_id: int, item_id: int):
    item = db.session.get(TecnicoLoteItem, item_id)
    if item is None or item.lote_id != lote_id or item.status != "gerado" or not item.arquivo_path:
        abort(404)
    caminho = Path(item.arquivo_path)
    if not caminho.exists():
        abort(404)
    return send_file(caminho, as_attachment=True, download_name=caminho.name)


@bp.route("/lote/<int:lote_id>/zip")
@login_required
def download_zip(lote_id: int):
    lote = db.session.get(TecnicoLote, lote_id)
    if lote is None:
        abort(404)
    caminho_zip = tecnico_service.montar_zip(lote)
    return send_file(caminho_zip, as_attachment=True, download_name=caminho_zip.name)


# ----------------------------------------------------------------------
# Configuração (admin)
# ----------------------------------------------------------------------


def _form_configuracao_preenchido() -> ConfiguracaoTecnicoForm:
    return ConfiguracaoTecnicoForm(
        nome_padrao=settings_service.get_tecnico_nome_padrao(),
        codigos_padrao=",".join(settings_service.get_tecnico_codigos_padrao()),
        periodo_dias_padrao=settings_service.get_tecnico_periodo_dias_padrao(),
    )


@bp.route("/configuracao")
@login_required
@roles_required("admin")
def configuracao():
    return render_template(
        "tecnico/configuracao.html", form=_form_configuracao_preenchido()
    )


@bp.route("/configuracao/salvar", methods=["POST"])
@login_required
@roles_required("admin")
def salvar_configuracao():
    form = ConfiguracaoTecnicoForm()
    if not form.validate_on_submit():
        flash("Configuração inválida — confira os campos destacados.", "warning")
        return render_template("tecnico/configuracao.html", form=form)

    settings_service.set(
        "tecnico_nome_padrao", (form.nome_padrao.data or "").strip(), updated_by_id=current_user.id
    )
    codigos = ",".join(_parse_codigos(form.codigos_padrao.data))
    settings_service.set("tecnico_codigos_padrao", codigos, updated_by_id=current_user.id)
    settings_service.set(
        "tecnico_periodo_dias_padrao",
        str(form.periodo_dias_padrao.data),
        updated_by_id=current_user.id,
    )

    audit_service.registrar(
        action="tecnico_config_saved",
        result="success",
        user=current_user,
        details={
            "nome_padrao": form.nome_padrao.data,
            "codigos_padrao": codigos,
            "periodo_dias_padrao": form.periodo_dias_padrao.data,
        },
    )
    db.session.commit()
    flash("Configuração do Relatório do Técnico salva.", "info")
    return redirect(url_for("tecnico.configuracao"))
