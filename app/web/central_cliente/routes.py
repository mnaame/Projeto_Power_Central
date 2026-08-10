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

from app.extensions import db, limiter
from app.integrations.auvo_painel_client import PainelCredentials
from app.models.central_cliente import CentralClienteLink, CentralClienteLote
from app.services import audit_service, central_cliente_service, settings_service
from app.services.report_xlsx import gerar_xlsx_central_cliente
from app.web.auth.decorators import roles_required
from app.web.central_cliente.forms import ConfiguracaoCentralForm, PrepararForm

bp = Blueprint("central_cliente", __name__, url_prefix="/central-cliente")

LOTES_HISTORICO_LIMITE = 20


def _lotes_recentes() -> list[CentralClienteLote]:
    return (
        CentralClienteLote.query.order_by(CentralClienteLote.criado_em.desc())
        .limit(LOTES_HISTORICO_LIMITE)
        .all()
    )


def _parse_ids_extra(bruto: str | None) -> list[int]:
    if not bruto:
        return []
    ids = []
    for pedaco in bruto.split(","):
        pedaco = pedaco.strip()
        if pedaco.isdigit():
            ids.append(int(pedaco))
    return ids


@bp.route("")
@login_required
@roles_required("admin")
def index():
    busca = (request.args.get("q") or "").strip()
    return render_template(
        "central_cliente/index.html",
        lotes=_lotes_recentes(),
        previa=None,
        form=PrepararForm(),
        simulacao=settings_service.central_simulacao(),
        auvo_user_request_padrao=settings_service.get_central_auvo_user_request(),
        busca=busca,
        resultados_busca=central_cliente_service.buscar_clientes(busca) if busca else None,
    )


@bp.route("/preparar", methods=["POST"])
@login_required
@roles_required("admin")
def preparar():
    form = PrepararForm()
    if not form.validate_on_submit():
        flash("Formulário inválido — confira o score mínimo.", "warning")
        return redirect(url_for("central_cliente.index"))

    score_minimo = form.score_minimo.data
    if score_minimo is None:
        score_minimo = settings_service.get_central_score_minimo()
    ids_extra = _parse_ids_extra(form.ids_extra.data)

    candidatos = central_cliente_service.montar_lote(score_minimo=score_minimo, ids_extra=ids_extra)
    previa = central_cliente_service.prever(candidatos)

    audit_service.registrar(
        action="central_lote_preparado",
        result="success",
        user=current_user,
        details={"total": len(previa), "score_minimo": score_minimo, "ids_extra": ids_extra},
    )
    db.session.commit()

    if not previa:
        flash("Nenhum cliente elegível encontrado com esses critérios.", "info")

    return render_template(
        "central_cliente/index.html",
        lotes=_lotes_recentes(),
        previa=previa,
        form=form,
        simulacao=settings_service.central_simulacao(),
        auvo_user_request_padrao=settings_service.get_central_auvo_user_request(),
        busca="",
        resultados_busca=None,
    )


@bp.route("/executar", methods=["POST"])
@login_required
@roles_required("admin")
@limiter.limit("5 per minute")
def executar():
    simulacao = settings_service.central_simulacao()

    total = request.form.get("total_linhas", type=int) or 0
    selecionadas_idx: set[int] = set()
    for bruto in request.form.getlist("selecionar"):
        try:
            selecionadas_idx.add(int(bruto))
        except ValueError:
            continue

    selecionados = []
    for i in range(total):
        if i not in selecionadas_idx:
            continue
        id_auvo_bruto = (request.form.get(f"id_auvo_{i}") or "").strip()
        if not id_auvo_bruto.isdigit():
            continue
        selecionados.append(
            {"id_auvo": int(id_auvo_bruto), "nome": (request.form.get(f"nome_{i}") or "").strip()}
        )

    if not selecionados:
        flash("Selecione ao menos um cliente antes de executar.", "warning")
        return redirect(url_for("central_cliente.index"))

    if not simulacao and request.form.get("confirmar") != "sim":
        flash(
            "Para executar de verdade (fora de simulação) é preciso marcar a "
            "confirmação — contatos reais serão criados na Auvo.",
            "warning",
        )
        return redirect(url_for("central_cliente.index"))

    credentials = None
    if not simulacao:
        cookie = (request.form.get("cookie") or "").strip()
        auvo_user_request = (request.form.get("auvo_user_request") or "").strip()
        if not cookie or not auvo_user_request:
            flash(
                "Fora de simulação é preciso colar o cookie de sessão e informar "
                "o auvo-user-request.",
                "warning",
            )
            return redirect(url_for("central_cliente.index"))
        credentials = PainelCredentials(cookie=cookie, auvo_user_request=auvo_user_request)

    try:
        lote = central_cliente_service.criar_lote(
            selecionados, simulacao=simulacao, user_id=current_user.id
        )
    except central_cliente_service.CentralClienteLoteVazioError:
        flash("Selecione ao menos um cliente antes de executar.", "warning")
        return redirect(url_for("central_cliente.index"))
    db.session.commit()  # o lote sobrevive mesmo se a execução falhar logo depois

    try:
        lote = central_cliente_service.executar_lote(
            lote, credentials=credentials, config=current_app.config, user=current_user
        )
    except central_cliente_service.CentralClienteLoteEmAndamentoError:
        flash("Este lote já está sendo executado.", "warning")
        return redirect(url_for("central_cliente.lote_detalhe", lote_id=lote.id))
    finally:
        # O cookie nunca sobrevive além desta requisição — nem em variável local.
        credentials = None

    audit_service.registrar(
        action="central_lote_executado",
        result="success" if lote.status in ("success", "parcial") else "failure",
        user=current_user,
        details={
            "lote_id": lote.id,
            "simulacao": lote.simulacao,
            "total_sucesso": lote.total_sucesso,
            "total_falha": lote.total_falha,
            "status": lote.status,
        },
    )
    db.session.commit()

    if lote.status == "success":
        flash(f"Lote executado: {lote.total_sucesso} link(s) criado(s).", "info")
    elif lote.status == "parcial":
        flash(
            f"Lote parcial: {lote.total_sucesso} criado(s), {lote.total_falha} com erro "
            f"(ou abortado por cookie expirado — confira o detalhe do lote).",
            "warning",
        )
    else:
        flash(f"Lote falhou: {lote.erro_mensagem or 'nenhum link foi criado.'}", "error")
    return redirect(url_for("central_cliente.lote_detalhe", lote_id=lote.id))


@bp.route("/lote/<int:lote_id>")
@login_required
@roles_required("admin")
def lote_detalhe(lote_id: int):
    lote = db.session.get(CentralClienteLote, lote_id)
    if lote is None:
        abort(404)
    return render_template("central_cliente/lote.html", lote=lote)


@bp.route("/lote/<int:lote_id>/item/<int:item_id>/whatsapp")
@login_required
@roles_required("admin")
def whatsapp(lote_id: int, item_id: int):
    """Nunca dispara nada sozinho: só audita que o link foi gerado/aberto
    e redireciona pro wa.me — quem confirma o envio é o humano, dentro do
    próprio WhatsApp (§5.5 do complemento). Sem telefone válido, 404 (o
    template já não deveria ter mostrado o botão)."""
    item = db.session.get(CentralClienteLink, item_id)
    if item is None or item.lote_id != lote_id:
        abort(404)

    link = central_cliente_service.montar_link_whatsapp_item(item, config=current_app.config)
    if link is None:
        abort(404)

    audit_service.registrar(
        action="central_whatsapp_aberto",
        result="success",
        user=current_user,
        details={"lote_id": lote_id, "id_auvo": item.id_auvo, "nome": item.nome},
    )
    db.session.commit()
    return redirect(link)


@bp.route("/exportar/<int:lote_id>")
@login_required
@roles_required("admin")
def exportar(lote_id: int):
    lote = db.session.get(CentralClienteLote, lote_id)
    if lote is None:
        abort(404)

    pasta = Path(current_app.instance_path) / "reports" / "central_cliente"
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    caminho = pasta / f"central_cliente_{lote_id}_{carimbo}.xlsx"

    linhas = [
        (
            item.nome,
            item.id_auvo,
            item.telefone or "",
            item.login or "",
            item.link_url or "",
            item.contato_codigo or "",
            item.status,
        )
        for item in lote.itens
    ]
    gerar_xlsx_central_cliente(caminho, linhas=linhas)

    audit_service.registrar(
        action="central_lote_exportado",
        result="success",
        user=current_user,
        details={"lote_id": lote_id},
    )
    db.session.commit()

    return send_file(caminho, as_attachment=True, download_name=caminho.name)


@bp.route("/configuracao")
@login_required
@roles_required("admin")
def configuracao():
    return render_template(
        "central_cliente/configuracao.html",
        form=_form_configuracao_preenchido(),
        simulacao=settings_service.central_simulacao(),
    )


def _form_configuracao_preenchido() -> ConfiguracaoCentralForm:
    return ConfiguracaoCentralForm(
        score_minimo=settings_service.get_central_score_minimo(),
        auvo_user_request=settings_service.get_central_auvo_user_request(),
        cargo_padrao=settings_service.get_central_cargo_padrao(),
        pausa_segundos=settings_service.get_central_pausa_segundos(),
        menu_solicitacoes=settings_service.central_menu_solicitacoes(),
        menu_os=settings_service.central_menu_os(),
        menu_orcamento=settings_service.central_menu_orcamento(),
        gerar_login_senha=settings_service.central_gerar_login_senha(),
    )


@bp.route("/configuracao/salvar", methods=["POST"])
@login_required
@roles_required("admin")
def salvar_configuracao():
    form = ConfiguracaoCentralForm()
    if not form.validate_on_submit():
        flash("Configuração inválida — confira os campos destacados.", "warning")
        return render_template(
            "central_cliente/configuracao.html",
            form=form,
            simulacao=settings_service.central_simulacao(),
        )

    settings_service.set(
        "central_score_minimo", str(form.score_minimo.data), updated_by_id=current_user.id
    )
    settings_service.set(
        "central_auvo_user_request",
        (form.auvo_user_request.data or "").strip(),
        updated_by_id=current_user.id,
    )
    settings_service.set(
        "central_cargo_padrao", form.cargo_padrao.data, updated_by_id=current_user.id
    )
    settings_service.set(
        "central_pausa_segundos", str(form.pausa_segundos.data), updated_by_id=current_user.id
    )
    settings_service.set(
        "central_menu_solicitacoes",
        "true" if form.menu_solicitacoes.data else "false",
        updated_by_id=current_user.id,
    )
    settings_service.set(
        "central_menu_os", "true" if form.menu_os.data else "false", updated_by_id=current_user.id
    )
    settings_service.set(
        "central_menu_orcamento",
        "true" if form.menu_orcamento.data else "false",
        updated_by_id=current_user.id,
    )
    settings_service.set(
        "central_gerar_login_senha",
        "true" if form.gerar_login_senha.data else "false",
        updated_by_id=current_user.id,
    )

    audit_service.registrar(
        action="central_config_saved",
        result="success",
        user=current_user,
        details={
            "score_minimo": form.score_minimo.data,
            "gerar_login_senha": form.gerar_login_senha.data,
        },
    )
    db.session.commit()
    flash("Configuração salva.", "info")
    return redirect(url_for("central_cliente.configuracao"))


@bp.route("/modo", methods=["POST"])
@login_required
@roles_required("admin")
def alternar_modo():
    """Simulação <-> Produção. Ligar produção cria contatos/links reais na
    Auvo, então exige confirmação explícita (mesma disciplina de
    auvo.alternar_modo)."""
    ligar_producao = request.form.get("modo") == "producao"
    if ligar_producao and request.form.get("confirmar") != "sim":
        flash(
            "Para ligar produção é preciso marcar a confirmação — contatos "
            "reais (com link de acesso sem senha) serão criados na Auvo.",
            "warning",
        )
        return redirect(url_for("central_cliente.configuracao"))

    settings_service.set(
        "central_simulacao", "false" if ligar_producao else "true", updated_by_id=current_user.id
    )
    audit_service.registrar(
        action="central_modo_alterado",
        result="success",
        user=current_user,
        details={"modo": "producao" if ligar_producao else "simulacao"},
    )
    db.session.commit()
    flash(
        "Modo PRODUÇÃO ligado — a próxima execução criará contatos reais na Auvo."
        if ligar_producao
        else "Modo simulação ligado — nada será enviado à Auvo.",
        "warning" if ligar_producao else "info",
    )
    return redirect(url_for("central_cliente.configuracao"))
