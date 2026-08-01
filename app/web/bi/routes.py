from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
from app.models.bi import BiRun
from app.services import audit_service, bi_service, settings_service
from app.services.report_xlsx import gerar_xlsx_bi_cronicos, gerar_xlsx_bi_intervencoes
from app.web.auth.decorators import roles_required
from app.web.bi.forms import ConfiguracaoBiForm

bp = Blueprint("bi", __name__, url_prefix="/bi")

HISTORICO_RUNS_LIMITE = 15
GRAFICO_LARGURA = 640
GRAFICO_ALTURA = 220
GRAFICO_MARGEM = 30


def _periodo_do_form() -> tuple[datetime, datetime]:
    preset = request.form.get("periodo", "padrao")
    agora = datetime.now(FUSO_HORARIO)
    if preset == "manual":
        inicio = datetime.strptime(request.form["inicio"], "%Y-%m-%d").replace(tzinfo=FUSO_HORARIO)
        fim = datetime.strptime(request.form["fim"], "%Y-%m-%d").replace(
            tzinfo=FUSO_HORARIO
        ) + timedelta(hours=23, minutes=59, seconds=59)
    else:
        dias = settings_service.get_bi_periodo_padrao_dias()
        fim = agora
        inicio = agora - timedelta(days=dias)
    if fim < inicio:
        raise ValueError("Período inválido: fim antes do início.")
    return inicio, fim


def _historico_runs() -> list[BiRun]:
    return BiRun.query.order_by(BiRun.criado_em.desc()).limit(HISTORICO_RUNS_LIMITE).all()


def _filtros_padrao() -> dict:
    return {
        "periodo_dias_padrao": settings_service.get_bi_periodo_padrao_dias(),
        "tecnico_padrao": settings_service.get_tecnico_nome_padrao(),
        "janela_dias_padrao": settings_service.get_bi_janela_dias(),
        "limiar_melhora_padrao": settings_service.get_bi_limiar_melhora(),
        "limiar_piora_padrao": settings_service.get_bi_limiar_piora(),
    }


def _barras_antes_depois(resumo_tecnicos) -> list[dict]:
    """Barras agrupadas (antes/depois) por técnico — mesma ideia do
    gráfico de linha do dashboard, mas em Python: calcula posições, o
    template só desenha `<rect>`."""
    if not resumo_tecnicos:
        return []
    maximo = max(
        max(r.antes_medio_por_dia, r.depois_medio_por_dia) for r in resumo_tecnicos
    ) or 1.0
    altura_util = GRAFICO_ALTURA - 2 * GRAFICO_MARGEM - 20
    largura_util = GRAFICO_LARGURA - 2 * GRAFICO_MARGEM
    n = len(resumo_tecnicos)
    grupo_largura = largura_util / n
    barra_largura = min(grupo_largura * 0.3, 36)
    base_y = GRAFICO_ALTURA - GRAFICO_MARGEM - 20

    barras = []
    for indice, resumo in enumerate(resumo_tecnicos):
        centro = GRAFICO_MARGEM + grupo_largura * (indice + 0.5)
        altura_antes = (resumo.antes_medio_por_dia / maximo) * altura_util
        altura_depois = (resumo.depois_medio_por_dia / maximo) * altura_util
        barras.append(
            {
                "tecnico": resumo.tecnico,
                "x_antes": round(centro - barra_largura - 2, 1),
                "x_depois": round(centro + 2, 1),
                "largura": round(barra_largura, 1),
                "y_antes": round(base_y - altura_antes, 1),
                "h_antes": round(max(altura_antes, 0.5), 1),
                "y_depois": round(base_y - altura_depois, 1),
                "h_depois": round(max(altura_depois, 0.5), 1),
                "label_x": round(centro, 1),
                "label_y": round(base_y + 14, 1),
                "antes_valor": resumo.antes_medio_por_dia,
                "depois_valor": resumo.depois_medio_por_dia,
            }
        )
    return barras


def _serie_tendencia(intervencoes) -> list[dict]:
    """Disparos/dia DEPOIS de cada visita, em ordem cronológica — cada
    ponto já é, por definição, um marco de visita (não precisamos de uma
    série semanal contínua, que exigiria persistir os eventos crus; ver
    docs/BI_EFICACIA_TECNICO.md)."""
    ordenadas = sorted(intervencoes, key=lambda i: i.marco)
    if not ordenadas:
        return []
    maximo = max(i.depois_por_dia for i in ordenadas) or 1.0
    n = len(ordenadas)
    passo = (GRAFICO_LARGURA - 2 * GRAFICO_MARGEM) / max(n - 1, 1)

    serie = []
    for indice, item in enumerate(ordenadas):
        x = GRAFICO_MARGEM + indice * passo
        y = GRAFICO_ALTURA - GRAFICO_MARGEM - (item.depois_por_dia / maximo) * (
            GRAFICO_ALTURA - 2 * GRAFICO_MARGEM
        )
        serie.append(
            {
                "x": round(x, 1),
                "y": round(y, 1),
                "valor": round(item.depois_por_dia, 3),
                "quando": item.marco,
                "loja": item.nome_loja,
                "tecnico": item.tecnico_nome,
            }
        )
    return serie


def _renderizar(run: BiRun | None):
    contexto = {
        "run": run,
        "historico": _historico_runs(),
        "kpis": None,
        "resumo_tecnicos": [],
        "cronicos": [],
        "intervencoes": [],
        "barras": [],
        "tendencia": [],
        "pontos_tendencia": "",
        "grafico_largura": GRAFICO_LARGURA,
        "grafico_altura": GRAFICO_ALTURA,
        **_filtros_padrao(),
    }
    if run is None or run.status != "success":
        return render_template("bi/index.html", **contexto)

    resumo_tecnicos = bi_service.resumo_por_tecnico(run)
    cronicos = bi_service.clientes_cronicos(run)
    intervencoes = list(run.intervencoes)
    resumo = run.resumo or {}

    com_base = resumo.get("melhorou", 0) + resumo.get("piorou", 0) + resumo.get("estavel", 0)
    pct_melhorou = (resumo.get("melhorou", 0) / com_base * 100) if com_base else None

    tendencia = _serie_tendencia(intervencoes)
    contexto.update(
        kpis={
            "total_intervencoes": resumo.get("total_intervencoes", 0),
            "pct_melhorou": pct_melhorou,
            "disparos_evitados": resumo.get("disparos_evitados_estimados", 0.0),
            "clientes_cronicos": len(cronicos),
            "sem_vinculo": resumo.get("sem_vinculo", 0),
            "sem_data": resumo.get("sem_data", 0),
        },
        resumo_tecnicos=resumo_tecnicos,
        cronicos=cronicos,
        intervencoes=intervencoes,
        barras=_barras_antes_depois(resumo_tecnicos),
        tendencia=tendencia,
        pontos_tendencia=" ".join(f"{p['x']},{p['y']}" for p in tendencia),
    )
    return render_template("bi/index.html", **contexto)


@bp.route("")
@login_required
def index():
    return _renderizar(bi_service.ultimo_run())


@bp.route("/run/<int:run_id>")
@login_required
def run_detalhe(run_id: int):
    run = bi_service.carregar_run(run_id)
    if run is None:
        abort(404)
    return _renderizar(run)


@bp.route("/recalcular", methods=["POST"])
@login_required
def recalcular():
    try:
        desde, hasta = _periodo_do_form()
    except (ValueError, KeyError):
        flash("Período inválido — confira as datas.", "warning")
        return redirect(url_for("bi.index"))

    tecnico = (request.form.get("tecnico") or "").strip()
    janela_dias = request.form.get("janela_dias", type=int)
    limiar_melhora = request.form.get("limiar_melhora", type=float)
    limiar_piora = request.form.get("limiar_piora", type=float)

    try:
        run = bi_service.recalcular(
            config=current_app.config,
            periodo_desde=desde,
            periodo_hasta=hasta,
            tecnico=tecnico,
            janela_dias=janela_dias,
            limiar_melhora_pct=limiar_melhora,
            limiar_piora_pct=limiar_piora,
            user_id=current_user.id,
        )
    except bi_service.BiRecalculoEmAndamentoError:
        flash("Já existe um recálculo do BI em andamento. Aguarde terminar.", "warning")
        return redirect(url_for("bi.index"))

    audit_service.registrar(
        action="bi_recalculado",
        result="success" if run.status == "success" else "failure",
        user=current_user,
        details={
            "run_id": run.id,
            "status": run.status,
            "periodo_desde": desde.isoformat(),
            "periodo_hasta": hasta.isoformat(),
            "tecnico": tecnico,
            "resumo": run.resumo,
            "erro": run.erro_mensagem,
        },
    )
    db.session.commit()

    if run.status == "success":
        total = (run.resumo or {}).get("total_intervencoes", 0)
        flash(f"BI recalculado: {total} intervenção(ões) no período.", "info")
    else:
        flash(f"Recálculo terminou com erro: {run.erro_mensagem}", "error")
    return redirect(url_for("bi.run_detalhe", run_id=run.id))


@bp.route("/exportar/<int:run_id>/<tabela>")
@login_required
def exportar(run_id: int, tabela: str):
    if tabela not in ("intervencoes", "cronicos"):
        abort(404)
    run = bi_service.carregar_run(run_id)
    if run is None:
        abort(404)

    pasta = Path(current_app.instance_path) / "reports" / "bi"
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    caminho = pasta / f"bi_{run_id}_{tabela}_{carimbo}.xlsx"

    if tabela == "intervencoes":
        linhas = [
            (
                item.marco.astimezone(FUSO_HORARIO).strftime("%d/%m/%Y %H:%M"),
                item.conta_power,
                item.nome_loja,
                item.tecnico_nome,
                round(item.antes_por_dia, 3),
                round(item.depois_por_dia, 3),
                round(item.variacao_pct, 1) if item.variacao_pct is not None else "",
                item.classificacao,
                "SIM" if item.parcial else "",
                "SIM" if item.atribuicao_compartilhada else "",
            )
            for item in run.intervencoes
        ]
        gerar_xlsx_bi_intervencoes(caminho, linhas=linhas)
    else:
        linhas = [
            (
                cronico.conta_power,
                cronico.nome_loja,
                cronico.total_visitas,
                cronico.ultima_classificacao,
                round(cronico.disparos_por_dia_atual, 3),
            )
            for cronico in bi_service.clientes_cronicos(run)
        ]
        gerar_xlsx_bi_cronicos(caminho, linhas=linhas)

    audit_service.registrar(
        action="bi_exportado",
        result="success",
        user=current_user,
        details={"run_id": run_id, "tabela": tabela},
    )
    db.session.commit()

    return send_file(caminho, as_attachment=True, download_name=caminho.name)


# ----------------------------------------------------------------------
# Configuração (admin)
# ----------------------------------------------------------------------


def _form_configuracao_preenchido() -> ConfiguracaoBiForm:
    return ConfiguracaoBiForm(
        janela_dias=settings_service.get_bi_janela_dias(),
        limiar_melhora=int(settings_service.get_bi_limiar_melhora()),
        limiar_piora=int(settings_service.get_bi_limiar_piora()),
        tipos_intervencao=",".join(str(t) for t in settings_service.get_bi_tipos_intervencao()),
        visitas_para_cronico=settings_service.get_bi_visitas_para_cronico(),
        periodo_padrao_dias=settings_service.get_bi_periodo_padrao_dias(),
        amostra_minima_tecnico=settings_service.get_bi_amostra_minima_tecnico(),
    )


@bp.route("/configuracao")
@login_required
@roles_required("admin")
def configuracao():
    return render_template("bi/configuracao.html", form=_form_configuracao_preenchido())


@bp.route("/configuracao/salvar", methods=["POST"])
@login_required
@roles_required("admin")
def salvar_configuracao():
    form = ConfiguracaoBiForm()
    if not form.validate_on_submit():
        flash("Configuração inválida — confira os campos destacados.", "warning")
        return render_template("bi/configuracao.html", form=form)

    settings_service.set("bi_janela_dias", str(form.janela_dias.data), updated_by_id=current_user.id)
    settings_service.set(
        "bi_limiar_melhora", str(form.limiar_melhora.data), updated_by_id=current_user.id
    )
    settings_service.set(
        "bi_limiar_piora", str(form.limiar_piora.data), updated_by_id=current_user.id
    )
    settings_service.set(
        "bi_tipos_intervencao", (form.tipos_intervencao.data or "").strip(), updated_by_id=current_user.id
    )
    settings_service.set(
        "bi_visitas_para_cronico",
        str(form.visitas_para_cronico.data),
        updated_by_id=current_user.id,
    )
    settings_service.set(
        "bi_periodo_padrao_dias", str(form.periodo_padrao_dias.data), updated_by_id=current_user.id
    )
    settings_service.set(
        "bi_amostra_minima_tecnico",
        str(form.amostra_minima_tecnico.data),
        updated_by_id=current_user.id,
    )

    audit_service.registrar(
        action="bi_config_saved",
        result="success",
        user=current_user,
        details={
            "janela_dias": form.janela_dias.data,
            "limiar_melhora": form.limiar_melhora.data,
            "limiar_piora": form.limiar_piora.data,
            "tipos_intervencao": form.tipos_intervencao.data,
            "visitas_para_cronico": form.visitas_para_cronico.data,
            "periodo_padrao_dias": form.periodo_padrao_dias.data,
            "amostra_minima_tecnico": form.amostra_minima_tecnico.data,
        },
    )
    db.session.commit()
    flash("Configuração do BI salva.", "info")
    return redirect(url_for("bi.configuracao"))
