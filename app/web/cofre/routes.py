from __future__ import annotations

from datetime import datetime, timedelta
from io import BytesIO

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

from app.domain import cofre_backup as dom_backup
from app.domain.cofre import gerar_senha
from app.domain.dates import FUSO_HORARIO
from app.extensions import db, limiter
from app.models.cofre import CATEGORIAS, Segredo
from app.services import audit_service, cofre_service
from app.web.auth.decorators import roles_required
from app.web.cofre.forms import SegredoForm

bp = Blueprint("cofre", __name__, url_prefix="/cofre")

# Um backup do cofre é texto curto; qualquer coisa muito maior que isso não
# é um backup nosso, e ler o arquivo inteiro na memória antes de descobrir
# seria um jeito bobo de derrubar o serviço.
LIMITE_ARQUIVO_BACKUP = 8 * 1024 * 1024


def _carregar_ou_abort(segredo_id: int):
    try:
        return cofre_service.obter_ou_negar(segredo_id, usuario=current_user)
    except cofre_service.CofreNaoEncontradoError:
        abort(404)
    except cofre_service.CofreAcessoNegadoError:
        audit_service.registrar(
            action="cofre_acesso_negado",
            result="failure",
            user=current_user,
            details={"segredo_id": segredo_id, "path": request.path},
        )
        db.session.commit()
        abort(403)


def _renderizar_lista(*, busca: str = "", categoria: str = "", revelado: dict | None = None):
    segredos = cofre_service.listar(usuario=current_user, busca=busca, categoria=categoria)
    hoje = datetime.now(FUSO_HORARIO).date()
    return render_template(
        "cofre/index.html",
        segredos=segredos,
        busca=busca,
        categoria=categoria,
        categorias=CATEGORIAS,
        revelado=revelado,
        hoje=hoje,
        hoje_mais_30=hoje + timedelta(days=30),
    )


@bp.route("")
@login_required
def index():
    busca = (request.args.get("busca") or "").strip()
    categoria = (request.args.get("categoria") or "").strip()
    return _renderizar_lista(busca=busca, categoria=categoria)


@bp.route("/<int:segredo_id>/revelar", methods=["POST"])
@login_required
@limiter.limit("10 per minute")
def revelar(segredo_id: int):
    """A senha nunca fica em redirect/flash/sessão — só na resposta direta
    desta requisição (a lista é re-renderizada aqui, na hora)."""
    segredo = _carregar_ou_abort(segredo_id)
    senha_reautenticacao = request.form.get("senha_reautenticacao", "")
    busca = (request.form.get("busca") or "").strip()
    categoria = (request.form.get("categoria") or "").strip()

    try:
        senha = cofre_service.revelar(
            segredo,
            usuario=current_user,
            senha_reautenticacao=senha_reautenticacao,
            config=current_app.config,
        )
    except cofre_service.CofreReautenticacaoInvalidaError:
        db.session.commit()
        flash("Senha incorreta — não foi possível revelar.", "warning")
        return redirect(url_for("cofre.index", busca=busca, categoria=categoria))
    except (cofre_service.CofreDecifraError, cofre_service.CofreSemChaveError) as exc:
        db.session.commit()
        flash(str(exc), "error")
        return redirect(url_for("cofre.index", busca=busca, categoria=categoria))

    db.session.commit()
    return _renderizar_lista(
        busca=busca, categoria=categoria, revelado={"id": segredo.id, "senha": senha}
    )


@bp.route("/novo", methods=["GET", "POST"])
@login_required
def novo():
    form = SegredoForm()
    senha_sugerida = gerar_senha()

    if form.validate_on_submit():
        if form.nivel.data == "restrito" and not current_user.is_admin:
            flash("Só administradores podem marcar um item como restrito.", "warning")
            return render_template(
                "cofre/form.html", form=form, titulo_pagina="Novo segredo",
                senha_sugerida=senha_sugerida,
            )
        if not form.senha.data:
            flash("Informe a senha (ou clique em \"Gerar senha forte\").", "warning")
            return render_template(
                "cofre/form.html", form=form, titulo_pagina="Novo segredo",
                senha_sugerida=senha_sugerida,
            )

        try:
            segredo = cofre_service.criar(
                titulo=form.titulo.data,
                categoria=form.categoria.data,
                login=form.login.data,
                senha=form.senha.data,
                url=form.url.data,
                notas=form.notas.data,
                nivel=form.nivel.data,
                expira_em=form.expira_em.data,
                user_id=current_user.id,
                config=current_app.config,
            )
        except cofre_service.CofreSemChaveError as exc:
            flash(str(exc), "error")
            return render_template(
                "cofre/form.html", form=form, titulo_pagina="Novo segredo",
                senha_sugerida=senha_sugerida,
            )
        audit_service.registrar(
            action="cofre_criado",
            result="success",
            user=current_user,
            details={"segredo_id": segredo.id, "titulo": segredo.titulo, "categoria": segredo.categoria, "nivel": segredo.nivel},
        )
        db.session.commit()
        flash("Segredo salvo no cofre.", "info")
        return redirect(url_for("cofre.index"))

    return render_template(
        "cofre/form.html", form=form, titulo_pagina="Novo segredo", senha_sugerida=senha_sugerida
    )


@bp.route("/<int:segredo_id>/editar", methods=["GET", "POST"])
@login_required
def editar(segredo_id: int):
    segredo = _carregar_ou_abort(segredo_id)
    senha_sugerida = gerar_senha()

    if request.method == "GET":
        form = SegredoForm(obj=segredo)
        form.senha.data = ""  # nunca preenche o campo de senha ao editar
        # `obj=` preenche por NOME do atributo, e no modelo a coluna é
        # `notas_cifradas` — então `notas` chegava vazia à tela. Pior que o
        # campo em branco: salvar de novo gravava vazio por cima e a nota
        # sumia de vez (relatado em produção).
        try:
            form.notas.data = cofre_service.notas_em_claro(
                segredo, config=current_app.config
            )
        except cofre_service.CofreDecifraError as exc:
            # Chave trocada: melhor avisar do que abrir o formulário em
            # branco e deixar o usuário apagar a nota sem perceber.
            flash(f"{exc} As notas não puderam ser carregadas.", "warning")
    else:
        form = SegredoForm()

    if form.validate_on_submit():
        if form.nivel.data == "restrito" and not current_user.is_admin:
            flash("Só administradores podem marcar um item como restrito.", "warning")
            return render_template(
                "cofre/form.html", form=form, titulo_pagina="Editar segredo", segredo=segredo,
                senha_sugerida=senha_sugerida,
            )

        try:
            cofre_service.atualizar(
                segredo,
                titulo=form.titulo.data,
                categoria=form.categoria.data,
                login=form.login.data,
                senha=form.senha.data,
                url=form.url.data,
                notas=form.notas.data,
                nivel=form.nivel.data,
                expira_em=form.expira_em.data,
                user_id=current_user.id,
                config=current_app.config,
            )
        except cofre_service.CofreSemChaveError as exc:
            db.session.rollback()
            flash(str(exc), "error")
            return render_template(
                "cofre/form.html", form=form, titulo_pagina="Editar segredo", segredo=segredo,
                senha_sugerida=senha_sugerida,
            )
        audit_service.registrar(
            action="cofre_editado",
            result="success",
            user=current_user,
            details={"segredo_id": segredo.id, "titulo": segredo.titulo, "categoria": segredo.categoria, "nivel": segredo.nivel},
        )
        db.session.commit()
        flash("Segredo atualizado.", "info")
        return redirect(url_for("cofre.index"))

    return render_template(
        "cofre/form.html", form=form, titulo_pagina="Editar segredo", segredo=segredo,
        senha_sugerida=senha_sugerida,
    )


@bp.route("/<int:segredo_id>/excluir", methods=["POST"])
@login_required
def excluir(segredo_id: int):
    segredo = _carregar_ou_abort(segredo_id)
    titulo = segredo.titulo
    cofre_service.excluir(segredo)
    audit_service.registrar(
        action="cofre_excluido",
        result="success",
        user=current_user,
        details={"segredo_id": segredo_id, "titulo": titulo},
    )
    db.session.commit()
    flash(f'"{titulo}" excluído do cofre.', "info")
    return redirect(url_for("cofre.index"))


@bp.route("/configuracao")
@login_required
@roles_required("admin")
def configuracao():
    chave_configurada = bool(current_app.config.get("VAULT_ENCRYPTION_KEY"))
    return render_template("cofre/configuracao.html", chave_configurada=chave_configurada)


# ----------------------------------------------------------------------
# Backup
#
# Só admin: o arquivo leva o cofre inteiro, itens `restrito` incluídos.
# O arquivo nunca é gravado no servidor — é montado em memória e enviado,
# para não deixar cópia do cofre em disco esperando alguém achar.
# ----------------------------------------------------------------------


@bp.route("/backup")
@login_required
@roles_required("admin")
def backup():
    return render_template(
        "cofre/backup.html",
        total_segredos=Segredo.query.count(),
        minimo_senha=dom_backup.MINIMO_SENHA_BACKUP,
    )


@bp.route("/backup/exportar", methods=["POST"])
@login_required
@roles_required("admin")
@limiter.limit("5 per minute")
def backup_exportar():
    senha_backup = request.form.get("senha_backup", "")
    confirmacao = request.form.get("senha_backup_confirmacao", "")

    if senha_backup != confirmacao:
        flash("As duas senhas do backup não são iguais.", "warning")
        return redirect(url_for("cofre.backup"))

    try:
        pacote = cofre_service.exportar_backup(
            usuario=current_user,
            senha_reautenticacao=request.form.get("senha_reautenticacao", ""),
            senha_backup=senha_backup,
            config=current_app.config,
        )
    except cofre_service.CofreReautenticacaoInvalidaError:
        db.session.commit()
        flash("Sua senha está incorreta — o backup não foi gerado.", "warning")
        return redirect(url_for("cofre.backup"))
    except dom_backup.BackupSenhaFracaError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("cofre.backup"))
    except (cofre_service.CofreDecifraError, cofre_service.CofreSemChaveError) as exc:
        flash(f"{exc} O backup não foi gerado.", "error")
        return redirect(url_for("cofre.backup"))

    db.session.commit()
    carimbo = datetime.now(FUSO_HORARIO).strftime("%Y%m%d_%H%M%S")
    return send_file(
        BytesIO(pacote),
        mimetype="application/json",
        as_attachment=True,
        download_name=f"cofre_backup_{carimbo}.json",
    )


def _conteudo_enviado():
    arquivo = request.files.get("arquivo")
    if arquivo is None or not arquivo.filename:
        return None
    return arquivo.read(LIMITE_ARQUIVO_BACKUP + 1)


@bp.route("/backup/restaurar", methods=["POST"])
@login_required
@roles_required("admin")
@limiter.limit("5 per minute")
def backup_restaurar():
    """Dois modos no mesmo formulário: "conferir" só abre o arquivo e diz o
    que tem dentro; "restaurar" grava. Conferir existe para o backup ser
    testado antes do dia em que ele for a única cópia."""
    conteudo = _conteudo_enviado()
    if conteudo is None:
        flash("Escolha o arquivo de backup.", "warning")
        return redirect(url_for("cofre.backup"))
    if len(conteudo) > LIMITE_ARQUIVO_BACKUP:
        flash("Arquivo grande demais para ser um backup do cofre.", "warning")
        return redirect(url_for("cofre.backup"))

    senha_backup = request.form.get("senha_backup", "")
    so_conferir = request.form.get("modo") != "restaurar"

    try:
        if so_conferir:
            info = cofre_service.conferir_backup(conteudo, senha_backup=senha_backup)
            flash(
                f"Arquivo válido: {info['itens']} senha(s), gerado em "
                f"{info['criado_em'][:19].replace('T', ' ')}. Nada foi alterado.",
                "info",
            )
            return redirect(url_for("cofre.backup"))

        resultado = cofre_service.restaurar_backup(
            conteudo,
            usuario=current_user,
            senha_reautenticacao=request.form.get("senha_reautenticacao", ""),
            senha_backup=senha_backup,
            substituir=request.form.get("substituir") == "on",
            config=current_app.config,
        )
    except cofre_service.CofreReautenticacaoInvalidaError:
        db.session.commit()
        flash("Sua senha está incorreta — nada foi restaurado.", "warning")
        return redirect(url_for("cofre.backup"))
    except (dom_backup.BackupSenhaInvalidaError, dom_backup.BackupFormatoInvalidoError) as exc:
        flash(str(exc), "warning")
        return redirect(url_for("cofre.backup"))
    except cofre_service.CofreSemChaveError as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("cofre.backup"))

    db.session.commit()
    flash(
        f"Restauração concluída: {resultado['adicionados']} adicionada(s), "
        f"{resultado['substituidos']} substituída(s), "
        f"{resultado['ignorados']} já existia(m).",
        "info",
    )
    return redirect(url_for("cofre.index"))
