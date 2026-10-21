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

from app.domain import bi_painel as dom_painel
from app.domain import graficos as dom_graficos
from app.domain.dates import FUSO_HORARIO
from app.extensions import db
from app.models.bi import BiRun
from app.services import audit_service, bi_service, settings_service
from app.services.report_xlsx import gerar_xlsx_bi_cronicos, gerar_xlsx_bi_intervencoes
from app.web.auth.decorators import roles_required
from app.web.bi.forms import ConfiguracaoBiForm

bp = Blueprint("bi", __name__, url_prefix="/bi")

HISTORICO_RUNS_LIMITE = 15

# Dois gráficos de tamanhos diferentes de propósito: o antes × depois tem
# duas colunas e não precisa de largura, a tendência tem uma por semana.
ANTES_DEPOIS_LARGURA = 300
ANTES_DEPOIS_ALTURA = 210
TENDENCIA_LARGURA = 660
TENDENCIA_ALTURA = 210


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


def _grafico_antes_depois(geral):
    """Duas colunas: a base comparável inteira, antes e depois.

    A cor do "depois" é função, não enfeite — verde se caiu, âmbar se
    subiu — e vem sempre com o rótulo da situação ao lado, porque cor
    sozinha não carrega significado (daltonismo, impressão, tema preto)."""
    if geral is None:
        return None
    classe_depois = "is-melhora" if geral.melhorou else "is-piora"
    return dom_graficos.montar_colunas(
        [
            ("Antes", geral.antes_por_dia, "is-neutro", "disparos/dia antes da visita"),
            ("Depois", geral.depois_por_dia, classe_depois, "disparos/dia depois da visita"),
        ],
        largura=ANTES_DEPOIS_LARGURA,
        altura=ANTES_DEPOIS_ALTURA,
        margem_esquerda=46,
        margem_direita=16,
    )


def _grafico_tendencia(semanas):
    """Uma coluna por semana. Série única: sem caixa de legenda — o
    título nomeia o que está plotado."""
    if not semanas:
        return None
    return dom_graficos.montar_colunas(
        [
            (
                semana.rotulo,
                semana.disparos_por_dia,
                "is-serie" if semana.visitas else "is-vazio",
                (
                    f"{semana.visitas} visita" + ("s" if semana.visitas > 1 else "")
                    if semana.visitas
                    else "nenhuma visita nesta semana"
                ),
            )
            for semana in semanas
        ],
        largura=TENDENCIA_LARGURA,
        altura=TENDENCIA_ALTURA,
        margem_esquerda=46,
        margem_direita=16,
    )


def _renderizar(run: BiRun | None):
    contexto = {
        "run": run,
        "historico": _historico_runs(),
        "kpis": None,
        "resumo_tecnicos": [],
        "cronicos": [],
        "intervencoes": [],
        "lojas": [],
        "placar": None,
        "funil": [],
        "frase": "",
        "evitados": None,
        "grafico_antes_depois": None,
        "grafico_tendencia": None,
        "glossario": dom_painel.GLOSSARIO,
        "rotulos_situacao": dom_painel.ROTULO_SITUACAO,
        "icones_situacao": dom_painel.ICONE_SITUACAO,
        **_filtros_padrao(),
    }
    if run is None or run.status != "success":
        return render_template("bi/index.html", **contexto)

    cronicos = bi_service.clientes_cronicos(run)
    intervencoes = list(run.intervencoes)
    resumo = run.resumo or {}

    lojas = dom_painel.lojas_por_resultado(
        intervencoes,
        limiar_melhora_pct=run.limiar_melhora_pct,
        limiar_piora_pct=run.limiar_piora_pct,
    )
    evitados = dom_painel.disparos_evitados(resumo.get("disparos_evitados_estimados", 0.0))

    contexto.update(
        kpis={
            "total_intervencoes": resumo.get("total_intervencoes", 0),
            "clientes_cronicos": len(cronicos),
            "sem_vinculo": resumo.get("sem_vinculo", 0),
            "sem_data": resumo.get("sem_data", 0),
        },
        resumo_tecnicos=bi_service.resumo_por_tecnico(run),
        cronicos=cronicos,
        intervencoes=intervencoes,
        lojas=lojas,
        placar=dom_painel.placar(lojas),
        funil=dom_painel.funil(resumo, lojas=lojas),
        frase=dom_painel.frase_resumo(
            tecnico=run.tecnico_filtro or "",
            total_intervencoes=resumo.get("total_intervencoes", 0),
            lojas=lojas,
            evitados=evitados,
            cronicos=len(cronicos),
        ),
        evitados=evitados,
        grafico_antes_depois=_grafico_antes_depois(dom_painel.antes_depois_geral(lojas)),
        grafico_tendencia=_grafico_tendencia(dom_painel.semanas(intervencoes)),
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
