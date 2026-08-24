from __future__ import annotations

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.integrations.telegram_client import TelegramError
from app.models.audit import AuditLog
from app.models.user import User
from app.security import hash_password
from app.services import audit_service, settings_service
from app.services.collector import criar_cliente_telegram
from app.web.admin.forms import ConfiguracoesForm, NovoUsuarioForm, TelegramForm, TrocarSenhaForm
from app.web.auth.decorators import roles_required

bp = Blueprint("admin", __name__, url_prefix="/admin")

AUDITORIA_POR_PAGINA = 30


@bp.route("/usuarios", methods=["GET", "POST"])
@login_required
@roles_required("admin")
def usuarios():
    form = NovoUsuarioForm()

    if form.validate_on_submit():
        username = form.username.data.strip()
        if User.query.filter_by(username=username).first():
            flash("Já existe um usuário com esse nome.", "warning")
        else:
            novo = User(
                username=username,
                password_hash=hash_password(form.password.data),
                role=form.role.data,
                active=True,
            )
            db.session.add(novo)
            audit_service.registrar(
                action="user_created",
                result="success",
                user=current_user,
                details={"username": novo.username, "role": novo.role},
            )
            db.session.commit()
            flash(f"Usuário '{novo.username}' criado.", "info")
            return redirect(url_for("admin.usuarios"))

    lista = User.query.order_by(User.username).all()
    return render_template("admin/usuarios.html", form=form, usuarios=lista)


@bp.route("/usuarios/<int:user_id>/alternar-status", methods=["POST"])
@login_required
@roles_required("admin")
def alternar_status(user_id: int):
    usuario = db.session.get(User, user_id)
    if usuario is None:
        abort(404)

    if usuario.id == current_user.id:
        flash("Você não pode desativar seu próprio usuário.", "warning")
        return redirect(url_for("admin.usuarios"))

    usuario.active = not usuario.active
    audit_service.registrar(
        action="user_status_changed",
        result="success",
        user=current_user,
        details={"username": usuario.username, "active": usuario.active},
    )
    db.session.commit()
    flash(f"Usuário '{usuario.username}' {'ativado' if usuario.active else 'desativado'}.", "info")
    return redirect(url_for("admin.usuarios"))


@bp.route("/usuarios/<int:user_id>/senha", methods=["POST"])
@login_required
@roles_required("admin")
def trocar_senha(user_id: int):
    usuario = db.session.get(User, user_id)
    if usuario is None:
        abort(404)

    form = TrocarSenhaForm()
    if form.validate_on_submit():
        usuario.password_hash = hash_password(form.password.data)
        audit_service.registrar(
            action="user_password_changed",
            result="success",
            user=current_user,
            details={"username": usuario.username},
        )
        db.session.commit()
        flash(f"Senha de '{usuario.username}' atualizada.", "info")
    else:
        flash("Não foi possível trocar a senha — use ao menos 8 caracteres.", "warning")
    return redirect(url_for("admin.usuarios"))


@bp.route("/configuracoes", methods=["GET"])
@login_required
@roles_required("admin")
def configuracoes():
    form = ConfiguracoesForm(
        window_hours=int(settings_service.get_window_hours()),
        confirming_codes=", ".join(settings_service.get_confirming_codes()),
        collector_interval_minutes=settings_service.get_collector_interval_minutes(),
        watchdog_threshold_minutes=int(settings_service.get_watchdog_threshold_minutes()),
        manual_cooldown_seconds=settings_service.get_manual_cooldown_seconds(),
        retention_days=settings_service.get_retention_days(),
        show_false_positives_in_panel=settings_service.show_false_positives_in_panel(),
        periodic_report_enabled=settings_service.periodic_report_enabled(),
        periodic_report_interval_minutes=settings_service.get_periodic_report_interval_minutes(),
        atend_codigos_evento=", ".join(settings_service.get_atend_codigos_evento()),
        atend_incluir_automaticos=settings_service.atend_incluir_automaticos(),
        atend_incluir_abertos=settings_service.atend_incluir_abertos(),
        atend_resolucao_indica_arme=", ".join(settings_service.get_atend_resolucao_indica_arme()),
        atend_horas_primeira_execucao=settings_service.get_atend_horas_primeira_execucao(),
        disp_horas_primeira_execucao=settings_service.get_disp_horas_primeira_execucao(),
        disp_limite_recorrente=settings_service.get_disp_limite_recorrente(),
        disp_ignorar_zonas=", ".join(settings_service.get_disp_ignorar_zonas()),
        dispg_limite_recorrente=settings_service.get_dispg_limite_recorrente(),
        dispg_grupo_villefort=", ".join(settings_service.get_dispg_grupo_villefort()),
        dispg_grupo_super_nosso=", ".join(settings_service.get_dispg_grupo_super_nosso()),
    )
    telegram_configurado = (
        settings_service.get_telegram_credentials(
            encryption_key=current_app.config["ENCRYPTION_KEY"]
        )
        is not None
    )
    return render_template(
        "admin/configuracoes.html",
        form=form,
        telegram_form=TelegramForm(),
        telegram_configurado=telegram_configurado,
    )


@bp.route("/configuracoes", methods=["POST"])
@login_required
@roles_required("admin")
def salvar_configuracoes():
    form = ConfiguracoesForm()
    if form.validate_on_submit():
        codigos = sorted({c.strip().upper() for c in form.confirming_codes.data.split(",") if c.strip()})

        settings_service.set(
            "window_hours", str(form.window_hours.data), updated_by_id=current_user.id
        )
        settings_service.set(
            "confirming_codes", ",".join(codigos), updated_by_id=current_user.id
        )
        settings_service.set(
            "collector_interval_minutes",
            str(form.collector_interval_minutes.data),
            updated_by_id=current_user.id,
        )
        settings_service.set(
            "watchdog_threshold_minutes",
            str(form.watchdog_threshold_minutes.data),
            updated_by_id=current_user.id,
        )
        settings_service.set(
            "manual_cooldown_seconds",
            str(form.manual_cooldown_seconds.data),
            updated_by_id=current_user.id,
        )
        settings_service.set(
            "retention_days", str(form.retention_days.data), updated_by_id=current_user.id
        )
        settings_service.set(
            "show_false_positives_in_panel",
            "true" if form.show_false_positives_in_panel.data else "false",
            updated_by_id=current_user.id,
        )
        settings_service.set(
            "periodic_report_enabled",
            "true" if form.periodic_report_enabled.data else "false",
            updated_by_id=current_user.id,
        )
        settings_service.set(
            "periodic_report_interval_minutes",
            str(form.periodic_report_interval_minutes.data),
            updated_by_id=current_user.id,
        )

        def _lista_normalizada(bruto: str, *, maiusculas: bool = False) -> str:
            itens = [item.strip() for item in bruto.split(",") if item.strip()]
            if maiusculas:
                itens = [item.upper() for item in itens]
            return ",".join(itens)

        settings_service.set(
            "atend_codigos_evento",
            _lista_normalizada(form.atend_codigos_evento.data, maiusculas=True),
            updated_by_id=current_user.id,
        )
        settings_service.set(
            "atend_incluir_automaticos",
            "true" if form.atend_incluir_automaticos.data else "false",
            updated_by_id=current_user.id,
        )
        settings_service.set(
            "atend_incluir_abertos",
            "true" if form.atend_incluir_abertos.data else "false",
            updated_by_id=current_user.id,
        )
        settings_service.set(
            "atend_resolucao_indica_arme",
            _lista_normalizada(form.atend_resolucao_indica_arme.data),
            updated_by_id=current_user.id,
        )
        settings_service.set(
            "atend_horas_primeira_execucao",
            str(form.atend_horas_primeira_execucao.data),
            updated_by_id=current_user.id,
        )
        settings_service.set(
            "disp_horas_primeira_execucao",
            str(form.disp_horas_primeira_execucao.data),
            updated_by_id=current_user.id,
        )
        settings_service.set(
            "disp_limite_recorrente",
            str(form.disp_limite_recorrente.data),
            updated_by_id=current_user.id,
        )
        settings_service.set(
            "disp_ignorar_zonas",
            _lista_normalizada(form.disp_ignorar_zonas.data, maiusculas=True),
            updated_by_id=current_user.id,
        )
        settings_service.set(
            "dispg_limite_recorrente",
            str(form.dispg_limite_recorrente.data),
            updated_by_id=current_user.id,
        )
        settings_service.set(
            "dispg_grupo_villefort",
            _lista_normalizada(form.dispg_grupo_villefort.data, maiusculas=True),
            updated_by_id=current_user.id,
        )
        settings_service.set(
            "dispg_grupo_super_nosso",
            _lista_normalizada(form.dispg_grupo_super_nosso.data, maiusculas=True),
            updated_by_id=current_user.id,
        )

        audit_service.registrar(
            action="settings_changed",
            result="success",
            user=current_user,
            details={
                "window_hours": form.window_hours.data,
                "confirming_codes": codigos,
                "collector_interval_minutes": form.collector_interval_minutes.data,
                "watchdog_threshold_minutes": form.watchdog_threshold_minutes.data,
                "manual_cooldown_seconds": form.manual_cooldown_seconds.data,
                "retention_days": form.retention_days.data,
                "show_false_positives_in_panel": form.show_false_positives_in_panel.data,
                "periodic_report_enabled": form.periodic_report_enabled.data,
                "periodic_report_interval_minutes": form.periodic_report_interval_minutes.data,
                "atend_codigos_evento": form.atend_codigos_evento.data,
                "atend_incluir_automaticos": form.atend_incluir_automaticos.data,
                "atend_incluir_abertos": form.atend_incluir_abertos.data,
                "atend_resolucao_indica_arme": form.atend_resolucao_indica_arme.data,
                "atend_horas_primeira_execucao": form.atend_horas_primeira_execucao.data,
                "disp_horas_primeira_execucao": form.disp_horas_primeira_execucao.data,
                "disp_limite_recorrente": form.disp_limite_recorrente.data,
                "disp_ignorar_zonas": form.disp_ignorar_zonas.data,
            },
        )
        db.session.commit()

        from app.scheduler import atualizar_intervalo_coletor

        atualizar_intervalo_coletor(form.collector_interval_minutes.data)

        flash("Configurações salvas.", "info")
    else:
        flash("Não foi possível salvar — verifique os campos destacados.", "warning")
    return redirect(url_for("admin.configuracoes"))


@bp.route("/configuracoes/telegram", methods=["POST"])
@login_required
@roles_required("admin")
def salvar_telegram():
    form = TelegramForm()
    if form.validate_on_submit() and form.bot_token.data and form.chat_id.data:
        settings_service.set_telegram_credentials(
            form.bot_token.data.strip(),
            form.chat_id.data.strip(),
            encryption_key=current_app.config["ENCRYPTION_KEY"],
            updated_by_id=current_user.id,
        )
        audit_service.registrar(
            action="telegram_settings_changed", result="success", user=current_user
        )
        db.session.commit()
        flash("Configuração do Telegram salva.", "info")
    else:
        flash("Informe o token do bot e o chat ID.", "warning")
    return redirect(url_for("admin.configuracoes"))


@bp.route("/configuracoes/telegram/testar", methods=["POST"])
@login_required
@roles_required("admin")
def testar_telegram():
    cliente = criar_cliente_telegram(current_app.config)
    if cliente is None:
        flash("Telegram não está configurado.", "warning")
        return redirect(url_for("admin.configuracoes"))

    try:
        cliente.enviar_mensagem("<b>Power Central</b>\nMensagem de teste — configuração ok.")
        audit_service.registrar(action="telegram_test", result="success", user=current_user)
        db.session.commit()
        flash("Mensagem de teste enviada ao grupo configurado.", "info")
    except TelegramError as exc:
        audit_service.registrar(
            action="telegram_test",
            result="failure",
            user=current_user,
            details={"erro": str(exc)},
        )
        db.session.commit()
        flash(f"Falha ao enviar mensagem de teste: {exc}", "error")

    return redirect(url_for("admin.configuracoes"))


@bp.route("/auditoria")
@login_required
@roles_required("admin")
def auditoria():
    pagina = request.args.get("pagina", 1, type=int)
    acao = request.args.get("acao") or None
    resultado = request.args.get("resultado") or None
    usuario_filtro = request.args.get("usuario") or None

    query = AuditLog.query
    if acao:
        query = query.filter(AuditLog.action == acao)
    if resultado:
        query = query.filter(AuditLog.result == resultado)
    if usuario_filtro:
        query = query.filter(AuditLog.username_attempted.ilike(f"%{usuario_filtro}%"))

    paginacao = query.order_by(AuditLog.timestamp.desc()).paginate(
        page=pagina, per_page=AUDITORIA_POR_PAGINA, error_out=False
    )

    acoes_disponiveis = [
        linha[0] for linha in db.session.query(AuditLog.action).distinct().order_by(AuditLog.action)
    ]

    return render_template(
        "admin/auditoria.html",
        paginacao=paginacao,
        acoes_disponiveis=acoes_disponiveis,
        filtro_acao=acao or "",
        filtro_resultado=resultado or "",
        filtro_usuario=usuario_filtro or "",
    )
