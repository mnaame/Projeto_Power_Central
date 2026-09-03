from __future__ import annotations

from datetime import datetime, timedelta

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

from app.domain.cofre import gerar_senha
from app.domain.dates import FUSO_HORARIO
from app.extensions import db, limiter
from app.models.cofre import CATEGORIAS
from app.services import audit_service, cofre_service
from app.web.auth.decorators import roles_required
from app.web.cofre.forms import SegredoForm

bp = Blueprint("cofre", __name__, url_prefix="/cofre")


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
