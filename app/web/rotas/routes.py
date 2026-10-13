"""Catálogo de visita preventiva por bairro — tela, importação e export.

O resultado fica em `session` entre o "gerar" e o "exportar" pelo mesmo
motivo do resto do sistema: a geração consulta duas plataformas e leva
tempo. Guardando, o export reusa o que já foi calculado em vez de
refazer tudo — e, principalmente, exporta **exatamente** o que está na
tela.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_login import current_user, login_required

from app.domain.planilhas import PlanilhaInvalida
from app.extensions import db
from app.integrations.softguard_client import SoftGuardError
from app.services import rotas_service
from app.services.report_xlsx import gerar_xlsx_rotas

bp = Blueprint("rotas", __name__, url_prefix="/rotas")

CHAVE_SESSAO = "rotas_resultado"

# 8 MB: o export da Auvo com 579 clientes tem 110 KB, e o relatório da
# PowerCentral 310 KB. O limite é folgado para crescer, e existe só para
# um arquivo trocado não virar um upload de gigabytes.
TAMANHO_MAXIMO = 8 * 1024 * 1024


def _serializar(resultado: dict) -> dict:
    """Formato leve para a sessão — dataclass não vai para JSON."""
    return {
        "resumo": resultado["resumo"],
        "regioes": [
            {
                "rotulo": regiao.rotulo,
                "tamanho": regiao.tamanho,
                "tem_bairro": regiao.tem_bairro,
                "cidade": regiao.cidade,
                "clientes": [
                    {
                        "conta": c.conta,
                        "nome": c.nome,
                        "bairro": c.bairro,
                        "cidade": c.cidade,
                        "fonte": c.fonte,
                    }
                    for c in regiao.clientes
                ],
            }
            for regiao in resultado["regioes"]
        ],
    }


@bp.route("")
@login_required
def index():
    return render_template(
        "rotas/index.html",
        resultado=session.get(CHAVE_SESSAO),
        importacoes=rotas_service.resumo_importacoes(),
    )


@bp.route("/gerar", methods=["POST"])
@login_required
def gerar():
    try:
        resultado = rotas_service.montar_catalogo(
            config=current_app.config, user=current_user
        )
    except (rotas_service.RotasError, SoftGuardError) as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("rotas.index"))

    db.session.commit()
    session[CHAVE_SESSAO] = _serializar(resultado)

    resumo = resultado["resumo"]
    if resumo["erro_auvo"]:
        flash(
            f"Endereços da Auvo indisponíveis ({resumo['erro_auvo']}) — "
            "usei o que estiver importado e a PowerCentral.",
            "warning",
        )
    flash(
        f"{resumo['regioes']} bairro(s) com {resumo['com_bairro']} cliente(s). "
        f"{resumo['sem_bairro']} sem bairro.",
        "info",
    )
    return redirect(url_for("rotas.index"))


@bp.route("/importar", methods=["POST"])
@login_required
def importar():
    """Importa o export da Auvo (.xlsx) ou o relatório de contas da
    PowerCentral (.xls). Qual é qual se descobre pelo conteúdo."""
    arquivo = request.files.get("arquivo")
    if arquivo is None or not arquivo.filename:
        flash("Escolha o arquivo da planilha.", "warning")
        return redirect(url_for("rotas.index"))

    conteudo = arquivo.read(TAMANHO_MAXIMO + 1)
    if len(conteudo) > TAMANHO_MAXIMO:
        flash("Arquivo acima de 8 MB — não parece ser o export de clientes.", "error")
        return redirect(url_for("rotas.index"))

    try:
        resumo = rotas_service.importar_planilha(conteudo, user=current_user)
    except PlanilhaInvalida as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("rotas.index"))

    db.session.commit()
    # O catálogo na sessão foi montado com os endereços de antes; mantê-lo
    # faria a tela mostrar o resultado antigo logo depois de importar, que
    # é exatamente a confusão que este módulo já causou uma vez.
    session.pop(CHAVE_SESSAO, None)

    rotulo = "Auvo" if resumo["fonte"] == rotas_service.FONTE_AUVO else "PowerCentral"
    flash(
        f"Planilha da {rotulo} importada: {resumo['lidas']} linha(s) lida(s), "
        f"{resumo['salvas']} com endereço, {resumo['com_bairro']} com bairro. "
        "Gere o catálogo de novo para usar.",
        "success",
    )
    return redirect(url_for("rotas.index"))


@bp.route("/exportar")
@login_required
def exportar():
    resultado = session.get(CHAVE_SESSAO)
    if not resultado:
        flash("Gere o catálogo antes de exportar.", "warning")
        return redirect(url_for("rotas.index"))

    pasta = Path(current_app.instance_path) / "reports" / "rotas"
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    caminho = pasta / f"visitas_por_bairro_{carimbo}.xlsx"

    gerar_xlsx_rotas(
        caminho,
        clientes=[
            (
                regiao["rotulo"],
                cliente["conta"],
                cliente["nome"],
                cliente["bairro"],
                cliente["cidade"],
                cliente["fonte"],
            )
            for regiao in resultado["regioes"]
            for cliente in regiao["clientes"]
        ],
        resumo=[
            (r["rotulo"], r["tamanho"], r["cidade"], "sim" if r["tem_bairro"] else "não")
            for r in resultado["regioes"]
        ],
        sem_bairro=[
            (c["conta"], c["nome"], c["cidade"] or "—")
            for r in resultado["regioes"]
            if not r["tem_bairro"]
            for c in r["clientes"]
        ],
    )
    return send_file(caminho, as_attachment=True, download_name=caminho.name)
