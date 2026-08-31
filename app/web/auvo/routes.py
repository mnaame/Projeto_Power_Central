from __future__ import annotations

from collections import Counter
from datetime import datetime, time, timedelta, timezone

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func

from app.domain.dates import FUSO_HORARIO
from app.extensions import db
from app.integrations.auvo_client import AuvoError
from app.models.auvo import AuvoChamado, AuvoDepara
from app.services import audit_service, auvo_service, report_service, settings_service, trigger_service
from app.web.auth.decorators import roles_required
from app.web.auvo.forms import ConfiguracaoAuvoForm, CredenciaisAuvoForm, TestarCriacaoForm

bp = Blueprint("auvo", __name__, url_prefix="/chamados")

HISTORICO_POR_PAGINA = 30

_CONFIG_KEYS = (
    "cooldown_horas",
    "sem_comunicacao_horas_minimas",
    "disparos_minimos_tarefa",
    "disp_geral_minimos_tarefa",
)
_TEMPLATE_KEYS = (
    ("template_semcom_titulo", "auvo_template_semcom_titulo"),
    ("template_semcom_descricao", "auvo_template_semcom_descricao"),
    ("template_disparos_titulo", "auvo_template_disparos_titulo"),
    ("template_disparos_descricao", "auvo_template_disparos_descricao"),
)

AUXILIARES = {
    "usuarios": ("Usuários da Auvo", "listar_usuarios"),
    "tipos": ("Tipos de tarefa da Auvo", "listar_tipos_tarefa"),
    "clientes": ("Clientes da Auvo", "listar_clientes"),
}


def _credenciais_configuradas() -> bool:
    return (
        auvo_service.criar_cliente(current_app.config) is not None
    )


# ----------------------------------------------------------------------
# Painel (operador + admin)
# ----------------------------------------------------------------------


@bp.route("")
@login_required
def painel():
    agora_utc = datetime.now(timezone.utc)
    inicio_hoje = (
        datetime.combine(datetime.now(FUSO_HORARIO).date(), time.min, tzinfo=FUSO_HORARIO)
        .astimezone(timezone.utc)
    )
    cooldown = settings_service.get_auvo_cooldown_horas()
    limite_cooldown = agora_utc - timedelta(hours=cooldown)

    abertas_hoje = (
        AuvoChamado.query.filter_by(resultado="aberta")
        .filter(AuvoChamado.criado_em >= inicio_hoje)
        .count()
    )
    simuladas_hoje = (
        AuvoChamado.query.filter_by(resultado="simulada")
        .filter(AuvoChamado.criado_em >= inicio_hoje)
        .count()
    )
    em_cooldown = (
        db.session.query(func.count(func.distinct(AuvoChamado.conta_power)))
        .filter(
            AuvoChamado.resultado == "aberta",
            AuvoChamado.criado_em >= limite_cooldown,
        )
        .scalar()
        or 0
    )
    ultimo = AuvoChamado.query.order_by(AuvoChamado.criado_em.desc()).first()

    pagina_atual = max(request.args.get("pagina", 1, type=int), 1)
    consulta = AuvoChamado.query.order_by(AuvoChamado.criado_em.desc())
    total = consulta.count()
    total_paginas = max((total + HISTORICO_POR_PAGINA - 1) // HISTORICO_POR_PAGINA, 1)
    historico = (
        consulta.offset((pagina_atual - 1) * HISTORICO_POR_PAGINA)
        .limit(HISTORICO_POR_PAGINA)
        .all()
    )

    return render_template(
        "auvo/painel.html",
        simulacao=settings_service.auvo_simulacao(),
        abertas_hoje=abertas_hoje,
        simuladas_hoje=simuladas_hoje,
        em_cooldown=em_cooldown,
        ultimo=ultimo,
        historico=historico,
        pagina_atual=pagina_atual,
        total_paginas=total_paginas,
        total=total,
    )


@bp.route("/verificar-agora", methods=["POST"])
@login_required
def verificar_agora():
    """Botão "Verificar tudo agora": roda, na hora, os dois gatilhos que
    alimentam a Auvo — o ciclo do coletor (sem comunicação, mesmo efeito do
    botão "Atualizar agora" do Painel) e o relatório de Disparos com a
    janela automática (desde o último até agora) — sem precisar visitar o
    Painel nem a aba de Disparos. Cada um tem seu próprio lock/cooldown;
    um bloqueado não impede o outro de rodar."""
    try:
        cycle = trigger_service.disparar_manual(config=current_app.config, user_id=current_user.id)
        audit_service.registrar(
            action="manual_update",
            result="success" if cycle.status == "success" else "failure",
            user=current_user,
            details={
                "cycle_id": cycle.id,
                "status": cycle.status,
                "error": cycle.error_message,
                "origem": "chamados",
            },
        )
        if cycle.status == "success":
            flash("Sem comunicação: verificado agora.", "info")
        else:
            flash(f"Sem comunicação terminou com erro: {cycle.error_message}", "warning")
    except trigger_service.CicloEmAndamentoError:
        flash("Sem comunicação: já havia uma verificação em andamento.", "warning")
    except trigger_service.CooldownAtivoError as exc:
        flash(f"Sem comunicação: aguarde mais {exc.segundos_restantes}s antes de verificar de novo.", "warning")

    try:
        run = report_service.gerar_disparos(config=current_app.config, user_id=current_user.id)
        audit_service.registrar(
            action="report_generated",
            result="success" if run.status == "success" else "failure",
            user=current_user,
            details={
                "module": "disparos",
                "run_id": run.id,
                "row_count": run.row_count,
                "error": run.error_message,
                "origem": "chamados",
            },
        )
        if run.status == "success":
            flash(f"Disparos: verificado agora ({run.row_count} cliente(s) no período).", "info")
        else:
            flash(f"Disparos terminou com erro: {run.error_message}", "warning")
    except report_service.RelatorioEmAndamentoError:
        flash("Disparos: já havia uma geração em andamento.", "warning")

    db.session.commit()
    return redirect(url_for("auvo.painel"))


# ----------------------------------------------------------------------
# Configuração (admin)
# ----------------------------------------------------------------------


def _form_configuracao_preenchido() -> ConfiguracaoAuvoForm:
    form = ConfiguracaoAuvoForm(
        criador_id=settings_service.get_auvo_criador_id(),
        responsavel_id=settings_service.get_auvo_responsavel_id(),
        atribuir_responsavel=settings_service.auvo_atribuir_responsavel(),
        task_type=settings_service.get_auvo_task_type(),
        task_type_sem_comunicacao=settings_service.get_auvo_task_type_sem_comunicacao(),
        priority=str(settings_service.get_auvo_priority()),
        cooldown_horas=settings_service.get_auvo_cooldown_horas(),
        sem_comunicacao_horas_minimas=settings_service.get_auvo_sem_comunicacao_horas_minimas(),
        disparos_minimos_tarefa=settings_service.get_auvo_disparos_minimos_tarefa(),
        disp_geral_minimos_tarefa=settings_service.get_auvo_disp_geral_minimos_tarefa(),
        template_semcom_titulo=settings_service.get_auvo_template("semcom", "titulo"),
        template_semcom_descricao=settings_service.get_auvo_template("semcom", "descricao"),
        template_disparos_titulo=settings_service.get_auvo_template("disparos", "titulo"),
        template_disparos_descricao=settings_service.get_auvo_template("disparos", "descricao"),
    )
    return form


def _render_configuracao(form=None, credenciais_form=None, testar_form=None, resultados_teste=None):
    primeiro_ok = (
        AuvoDepara.query.filter(AuvoDepara.status == "OK", AuvoDepara.id_auvo.isnot(None))
        .order_by(AuvoDepara.conta_power)
        .first()
    )
    return render_template(
        "auvo/configuracao.html",
        form=form or _form_configuracao_preenchido(),
        credenciais_form=credenciais_form or CredenciaisAuvoForm(),
        testar_form=testar_form or TestarCriacaoForm(
            customer_id=primeiro_ok.id_auvo if primeiro_ok else None
        ),
        simulacao=settings_service.auvo_simulacao(),
        credenciais_configuradas=_credenciais_configuradas(),
        resultados_teste=resultados_teste,
    )


@bp.route("/configuracao")
@login_required
@roles_required("admin")
def configuracao():
    return _render_configuracao()


@bp.route("/configuracao/salvar", methods=["POST"])
@login_required
@roles_required("admin")
def salvar_configuracao():
    form = ConfiguracaoAuvoForm()
    if not form.validate_on_submit():
        flash("Configuração inválida — confira os campos destacados.", "warning")
        return _render_configuracao(form=form)

    def _opcional(valor) -> str:
        return "" if valor is None else str(valor)

    settings_service.set("auvo_criador_id", _opcional(form.criador_id.data), updated_by_id=current_user.id)
    settings_service.set("auvo_responsavel_id", _opcional(form.responsavel_id.data), updated_by_id=current_user.id)
    settings_service.set(
        "auvo_atribuir_responsavel",
        "true" if form.atribuir_responsavel.data else "false",
        updated_by_id=current_user.id,
    )
    settings_service.set("auvo_task_type", _opcional(form.task_type.data), updated_by_id=current_user.id)
    settings_service.set(
        "auvo_task_type_sem_comunicacao",
        _opcional(form.task_type_sem_comunicacao.data),
        updated_by_id=current_user.id,
    )
    settings_service.set("auvo_priority", form.priority.data, updated_by_id=current_user.id)
    for campo in _CONFIG_KEYS:
        settings_service.set(
            f"auvo_{campo}", str(getattr(form, campo).data), updated_by_id=current_user.id
        )
    for campo_form, chave in _TEMPLATE_KEYS:
        settings_service.set(chave, getattr(form, campo_form).data, updated_by_id=current_user.id)

    audit_service.registrar(
        action="auvo_config_saved",
        result="success",
        user=current_user,
        details={
            "criador_id": form.criador_id.data,
            "task_type": form.task_type.data,
            "task_type_sem_comunicacao": form.task_type_sem_comunicacao.data,
        },
    )
    db.session.commit()
    flash("Configuração da Auvo salva.", "info")
    return redirect(url_for("auvo.configuracao"))


@bp.route("/configuracao/credenciais", methods=["POST"])
@login_required
@roles_required("admin")
def salvar_credenciais():
    form = CredenciaisAuvoForm()
    if not form.validate_on_submit():
        flash("Informe API Key e API Token.", "warning")
        return _render_configuracao(credenciais_form=form)

    settings_service.set_auvo_credentials(
        form.api_key.data.strip(),
        form.api_token.data.strip(),
        encryption_key=current_app.config["ENCRYPTION_KEY"],
        updated_by_id=current_user.id,
    )
    audit_service.registrar(
        action="auvo_credentials_saved", result="success", user=current_user
    )
    db.session.commit()
    flash("Credenciais da Auvo salvas (cifradas).", "info")
    return redirect(url_for("auvo.configuracao"))


@bp.route("/modo", methods=["POST"])
@login_required
@roles_required("admin")
def alternar_modo():
    """Simulação ↔ Produção. Ligar produção despacha técnico de verdade,
    então exige a confirmação explícita (checkbox)."""
    ligar_producao = request.form.get("modo") == "producao"
    if ligar_producao and request.form.get("confirmar") != "sim":
        flash(
            "Para ligar o modo produção é preciso marcar a confirmação — "
            "tarefas reais serão abertas na Auvo.",
            "warning",
        )
        return redirect(url_for("auvo.configuracao"))

    settings_service.set(
        "auvo_simulacao", "false" if ligar_producao else "true", updated_by_id=current_user.id
    )
    audit_service.registrar(
        action="auvo_mode_changed",
        result="success",
        user=current_user,
        details={"modo": "producao" if ligar_producao else "simulacao"},
    )
    db.session.commit()
    flash(
        "Modo PRODUÇÃO ligado — chamados reais serão abertos."
        if ligar_producao
        else "Modo simulação ligado — nada será enviado à Auvo.",
        "warning" if ligar_producao else "info",
    )
    return redirect(url_for("auvo.configuracao"))


@bp.route("/testar", methods=["POST"])
@login_required
@roles_required("admin")
def testar_criacao():
    form = TestarCriacaoForm()
    if not form.validate_on_submit():
        flash("ID de cliente inválido.", "warning")
        return _render_configuracao(testar_form=form)

    resultados = auvo_service.testar_criacao(
        config=current_app.config,
        customer_id=form.customer_id.data,
        origem_user_id=current_user.id,
    )
    audit_service.registrar(
        action="auvo_teste_criacao",
        result="success" if all(r.get("ok") for r in resultados) else "failure",
        user=current_user,
        details={"niveis": [{k: r.get(k) for k in ("nivel", "ok", "detalhe")} for r in resultados]},
    )
    db.session.commit()
    return _render_configuracao(testar_form=form, resultados_teste=resultados)


@bp.route("/auxiliares/<tipo>")
@login_required
@roles_required("admin")
def auxiliares(tipo: str):
    if tipo not in AUXILIARES:
        abort(404)
    titulo, metodo = AUXILIARES[tipo]

    client = auvo_service.criar_cliente(current_app.config)
    if client is None:
        flash("Configure as credenciais da Auvo primeiro.", "warning")
        return redirect(url_for("auvo.configuracao"))

    try:
        itens = getattr(client, metodo)()
    except AuvoError as exc:
        flash(f"Erro ao consultar a Auvo: {exc}", "error")
        return redirect(url_for("auvo.configuracao"))

    linhas = [
        {
            "id": _chave(item, ("id", "userID", "userId", "customerId", "idCustomer")),
            "nome": _chave(
                item, ("name", "description", "nome", "razaoSocial", "corporateName")
            ),
            "extra": _chave(item, ("email", "address", "externalId")),
        }
        for item in itens
    ]
    return render_template("auvo/auxiliares.html", titulo=titulo, linhas=linhas, tipo=tipo)


def _chave(item: dict, chaves: tuple[str, ...]) -> str:
    for chave in chaves:
        valor = item.get(chave)
        if valor not in (None, ""):
            return str(valor)
    return ""


# ----------------------------------------------------------------------
# De-para (admin)
# ----------------------------------------------------------------------


@bp.route("/depara")
@login_required
@roles_required("admin")
def depara():
    filtro = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "").strip().upper()
    so_suprimidas = request.args.get("suprimidas") == "1"
    agora = datetime.now(timezone.utc)

    consulta = AuvoDepara.query
    if filtro:
        padrao = f"%{filtro}%"
        consulta = consulta.filter(
            db.or_(
                AuvoDepara.conta_power.ilike(padrao),
                AuvoDepara.nome_power.ilike(padrao),
                AuvoDepara.nome_auvo.ilike(padrao),
            )
        )
    if status in ("OK", "REVISAR", "NAO"):
        consulta = consulta.filter(AuvoDepara.status == status)
    linhas = consulta.order_by(AuvoDepara.conta_power).all()

    if so_suprimidas:
        linhas = [linha for linha in linhas if linha.esta_suprimido(agora)]

    contagem_ids = Counter(
        linha.id_auvo for linha in AuvoDepara.query.all() if linha.id_auvo is not None
    )
    duplicados = {id_auvo for id_auvo, total in contagem_ids.items() if total > 1}
    contagens = dict(
        db.session.query(AuvoDepara.status, func.count()).group_by(AuvoDepara.status).all()
    )
    total_suprimidas = sum(
        1 for linha in AuvoDepara.query.all() if linha.esta_suprimido(agora)
    )

    return render_template(
        "auvo/depara.html",
        linhas=linhas,
        filtro=filtro,
        status_filtro=status,
        so_suprimidas=so_suprimidas,
        duplicados=duplicados,
        contagens=contagens,
        total_suprimidas=total_suprimidas,
        agora=agora,
    )


@bp.route("/depara/<int:linha_id>", methods=["POST"])
@login_required
@roles_required("admin")
def editar_depara(linha_id: int):
    linha = db.session.get(AuvoDepara, linha_id)
    if linha is None:
        abort(404)

    id_auvo_bruto = (request.form.get("id_auvo") or "").strip()
    status = (request.form.get("status") or "").strip().upper()
    if status not in ("OK", "REVISAR", "NAO"):
        flash("Status inválido.", "warning")
        return redirect(url_for("auvo.depara"))
    try:
        id_auvo = int(id_auvo_bruto) if id_auvo_bruto else None
    except ValueError:
        flash("ID Auvo precisa ser numérico.", "warning")
        return redirect(url_for("auvo.depara"))

    anterior = {"id_auvo": linha.id_auvo, "status": linha.status}
    linha.id_auvo = id_auvo
    linha.status = status
    linha.updated_by_user_id = current_user.id
    audit_service.registrar(
        action="auvo_depara_edited",
        result="success",
        user=current_user,
        details={
            "conta": linha.conta_power,
            "de": anterior,
            "para": {"id_auvo": id_auvo, "status": status},
        },
    )
    db.session.commit()
    flash(f"Vínculo da conta {linha.conta_power} atualizado.", "info")
    return redirect(url_for("auvo.depara", q=request.form.get("q", ""), status=request.form.get("status_filtro", "")))


def _redirect_depara():
    return redirect(
        url_for(
            "auvo.depara",
            q=request.form.get("q", ""),
            status=request.form.get("status_filtro", ""),
            suprimidas=request.form.get("so_suprimidas", ""),
        )
    )


@bp.route("/depara/<int:linha_id>/suprimir", methods=["POST"])
@login_required
@roles_required("admin")
def suprimir_depara(linha_id: int):
    """Pausa a abertura de chamados desta conta (problema já sendo tratado
    em campo). Data opcional: sem data = pausa até liberar na mão; com
    data = volta a abrir sozinha depois dela."""
    linha = db.session.get(AuvoDepara, linha_id)
    if linha is None:
        abort(404)

    ate_bruto = (request.form.get("suprimido_ate") or "").strip()
    ate = None
    if ate_bruto:
        try:
            # a data marca o último dia pausado — libera na virada do dia seguinte
            dia = datetime.strptime(ate_bruto, "%Y-%m-%d")
            ate = dia.replace(hour=23, minute=59, second=59, tzinfo=FUSO_HORARIO)
        except ValueError:
            flash("Data de supressão inválida.", "warning")
            return _redirect_depara()

    linha.suprimido = True
    linha.suprimido_ate = ate
    linha.suprimido_motivo = (request.form.get("motivo") or "").strip() or None
    linha.updated_by_user_id = current_user.id
    audit_service.registrar(
        action="auvo_depara_suprimida",
        result="success",
        user=current_user,
        details={
            "conta": linha.conta_power,
            "ate": ate.isoformat() if ate else None,
            "motivo": linha.suprimido_motivo,
        },
    )
    db.session.commit()
    flash(f"Conta {linha.conta_power} pausada — não abrirá chamado.", "info")
    return _redirect_depara()


@bp.route("/depara/<int:linha_id>/liberar", methods=["POST"])
@login_required
@roles_required("admin")
def liberar_depara(linha_id: int):
    linha = db.session.get(AuvoDepara, linha_id)
    if linha is None:
        abort(404)

    linha.suprimido = False
    linha.suprimido_ate = None
    linha.suprimido_motivo = None
    linha.updated_by_user_id = current_user.id
    audit_service.registrar(
        action="auvo_depara_liberada",
        result="success",
        user=current_user,
        details={"conta": linha.conta_power},
    )
    db.session.commit()
    flash(f"Conta {linha.conta_power} liberada — volta a abrir chamado.", "info")
    return _redirect_depara()


@bp.route("/depara/importar", methods=["POST"])
@login_required
@roles_required("admin")
def importar_depara():
    arquivo = request.files.get("arquivo")
    if arquivo is None or not arquivo.filename:
        flash("Escolha o arquivo CSV do de-para.", "warning")
        return redirect(url_for("auvo.depara"))

    try:
        conteudo = arquivo.read().decode("utf-8-sig")
        resultado = auvo_service.importar_depara_csv(conteudo, updated_by_id=current_user.id)
    except Exception as exc:
        flash(f"Falha ao importar o CSV: {exc}", "error")
        return redirect(url_for("auvo.depara"))

    audit_service.registrar(
        action="auvo_depara_imported", result="success", user=current_user, details=resultado
    )
    db.session.commit()
    flash(
        f"De-para importado: {resultado['criadas']} nova(s), "
        f"{resultado['atualizadas']} atualizada(s).",
        "info",
    )
    return redirect(url_for("auvo.depara"))


@bp.route("/depara/regerar", methods=["POST"])
@login_required
@roles_required("admin")
def regerar_depara():
    client = auvo_service.criar_cliente(current_app.config)
    if client is None:
        flash("Configure as credenciais da Auvo primeiro.", "warning")
        return redirect(url_for("auvo.depara"))

    try:
        resultado = auvo_service.regerar_depara(client=client, updated_by_id=current_user.id)
    except AuvoError as exc:
        flash(f"Erro ao consultar clientes da Auvo: {exc}", "error")
        return redirect(url_for("auvo.depara"))

    audit_service.registrar(
        action="auvo_depara_regenerated", result="success", user=current_user, details=resultado
    )
    db.session.commit()
    flash(
        f"De-para regerado: {resultado['recasadas']} recasada(s), "
        f"{resultado['preservadas']} preservada(s) (já revisadas).",
        "info",
    )
    return redirect(url_for("auvo.depara"))
