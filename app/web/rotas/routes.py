"""Catálogo de visita preventiva por bairro — tela, importação e export.

O catálogo vive no **banco**, não na sessão. A versão anterior guardava o
resultado no cookie de sessão: com a base real ele dava 4.746 bytes
contra um limite de 4.093 no navegador, o cookie era descartado calado, e
a tela respondia "nenhum catálogo gerado ainda" logo depois de gerar.
Guardar no banco também é o que dá memória à rodada — a marca do que já
foi visitado tem que sobreviver a fechar o navegador.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required

from app.domain.planilhas import PlanilhaInvalida
from app.extensions import db
from app.integrations.softguard_client import SoftGuardError
from app.services import rotas_service
from app.services.report_xlsx import gerar_xlsx_rotas

bp = Blueprint("rotas", __name__, url_prefix="/rotas")

# 8 MB: o export da Auvo com 579 clientes tem 110 KB, e o relatório da
# PowerCentral 310 KB. O limite é folgado para crescer, e existe só para
# um arquivo trocado não virar um upload de gigabytes.
TAMANHO_MAXIMO = 8 * 1024 * 1024


def _pontos_do_mapa(dados: dict) -> list[dict]:
    """Só os clientes com coordenada — quem não tem não vira um pino no
    meio do nada, continua na lista e na busca.

    Os pontos vão para o JS por `data-attribute`, e não por uma chamada à
    API: a tela já tem o catálogo renderizado, e buscar de novo seria
    refazer uma consulta que já foi feita."""
    linhas = dados.get("linhas") or {}
    pontos = []
    for regiao in dados.get("regioes", []):
        for cliente in regiao.clientes:
            if not cliente.tem_coordenada:
                continue
            linha = linhas.get(cliente.conta)
            pontos.append(
                {
                    "conta": cliente.conta,
                    "nome": cliente.nome,
                    "regiao": regiao.rotulo,
                    "bairro": cliente.bairro,
                    "cidade": cliente.cidade,
                    "lat": cliente.lat,
                    "lon": cliente.lon,
                    "visitado": bool(linha is not None and linha.visitado_em),
                }
            )
    return pontos


@bp.route("")
@login_required
def index():
    ciclo = rotas_service.ciclo_atual()
    dados = rotas_service.catalogo(ciclo)
    importacoes = rotas_service.resumo_importacoes()
    return render_template(
        "rotas/index.html",
        ciclo=ciclo,
        catalogo=dados,
        pontos=_pontos_do_mapa(dados),
        bairros=rotas_service.bairros_conhecidos(),
        importacoes=importacoes,
        # Planilha importada e nenhuma coordenada nela = enviada antes de
        # o sistema passar a ler esse campo. É a causa mais provável de um
        # mapa vazio, e a tela diz isso em vez de deixar adivinhar.
        sem_coordenada_importada=bool(importacoes)
        and not any(item["com_coordenada"] for item in importacoes),
    )


@bp.route("/gerar", methods=["POST"])
@login_required
def gerar():
    try:
        ciclo = rotas_service.montar_catalogo(
            config=current_app.config, user=current_user
        )
    except (rotas_service.RotasError, SoftGuardError) as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("rotas.index"))

    db.session.commit()
    resumo = ciclo.resumo or {}
    if resumo.get("erro_auvo"):
        flash(
            f"Endereços da Auvo indisponíveis ({resumo['erro_auvo']}) — "
            "usei o que estiver importado e a PowerCentral.",
            "warning",
        )
    flash(
        f"Ciclo #{ciclo.numero}: {resumo.get('regioes', 0)} bairro(s) com "
        f"{resumo.get('com_bairro', 0)} cliente(s). "
        f"{resumo.get('sem_bairro', 0)} sem bairro.",
        "info",
    )
    return redirect(url_for("rotas.index"))


@bp.route("/visita", methods=["POST"])
@login_required
def visita():
    """Marca ou desmarca uma visita.

    Responde JSON quando o pedido vem do JS (a tela marca sem recarregar,
    que é o que torna viável percorrer uma lista de cem clientes) e
    redireciona quando vem de um `form` comum — sem JS a tela continua
    inteira, só mais lenta."""
    ciclo = rotas_service.ciclo_atual()
    conta = (request.form.get("conta") or "").strip()
    visitado = request.form.get("visitado") == "1"
    quer_json = request.accept_mimetypes.best == "application/json"

    if ciclo is None:
        if quer_json:
            return jsonify({"erro": "Nenhum ciclo em aberto."}), 400
        flash("Gere o catálogo antes de marcar visitas.", "warning")
        return redirect(url_for("rotas.index"))

    try:
        rotas_service.marcar_visita(ciclo, conta, visitado=visitado, user=current_user)
    except rotas_service.RotasError as exc:
        db.session.rollback()
        if quer_json:
            return jsonify({"erro": str(exc)}), 404
        flash(str(exc), "error")
        return redirect(url_for("rotas.index"))

    db.session.commit()
    if quer_json:
        dados = rotas_service.catalogo(ciclo)
        return jsonify(
            {"conta": conta, "visitado": visitado,
             "visitados": dados["visitados"], "total": dados["total"]}
        )
    return redirect(url_for("rotas.index"))


@bp.route("/bairro", methods=["POST"])
@login_required
def bairro():
    """Corrige o bairro de um cliente à mão.

    Responde JSON para o JS atualizar a linha sem recarregar, e
    redireciona quando vem de um `form` comum."""
    ciclo = rotas_service.ciclo_atual()
    conta = (request.form.get("conta") or "").strip()
    quer_json = request.accept_mimetypes.best == "application/json"

    try:
        resultado = rotas_service.definir_bairro_manual(
            ciclo,
            conta,
            bairro=request.form.get("bairro", ""),
            cidade=request.form.get("cidade", ""),
            user=current_user,
        )
    except rotas_service.RotasError as exc:
        db.session.rollback()
        if quer_json:
            return jsonify({"erro": str(exc)}), 404
        flash(str(exc), "error")
        return redirect(url_for("rotas.index"))

    db.session.commit()
    if quer_json:
        return jsonify(resultado)
    if resultado["bairro"]:
        flash(
            f"Conta {conta}: bairro definido como {resultado['bairro']}. "
            "A correção vale também nas próximas gerações.",
            "success",
        )
    else:
        flash(f"Conta {conta}: correção removida, voltou a valer o cadastro.", "info")
    return redirect(url_for("rotas.index"))


@bp.route("/reiniciar", methods=["POST"])
@login_required
def reiniciar():
    ciclo = rotas_service.ciclo_atual()
    if ciclo is None:
        flash("Não há ciclo para reiniciar.", "warning")
        return redirect(url_for("rotas.index"))

    novo = rotas_service.reiniciar_ciclo(ciclo, user=current_user)
    db.session.commit()
    flash(
        f"Ciclo #{ciclo.numero} encerrado. Começou o #{novo.numero} com as "
        "mesmas contas e nenhuma visita marcada.",
        "success",
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
    ciclo = rotas_service.ciclo_atual()
    dados = rotas_service.catalogo(ciclo)
    if not dados["regioes"]:
        flash("Gere o catálogo antes de exportar.", "warning")
        return redirect(url_for("rotas.index"))

    linhas = dados["linhas"]

    def _visita(conta: str) -> str:
        linha = linhas.get(conta)
        if linha is None or linha.visitado_em is None:
            return ""
        return linha.visitado_em.strftime("%d/%m/%Y %H:%M")

    pasta = Path(current_app.instance_path) / "reports" / "rotas"
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    caminho = pasta / f"visitas_por_bairro_ciclo{ciclo.numero}_{carimbo}.xlsx"

    gerar_xlsx_rotas(
        caminho,
        clientes=[
            (
                regiao.rotulo,
                cliente.conta,
                cliente.nome,
                cliente.bairro,
                cliente.cidade,
                cliente.fonte,
                _visita(cliente.conta),
            )
            for regiao in dados["regioes"]
            for cliente in regiao.clientes
        ],
        resumo=[
            (
                regiao.rotulo,
                regiao.tamanho,
                sum(1 for c in regiao.clientes if _visita(c.conta)),
                regiao.cidade,
                "sim" if regiao.tem_bairro else "não",
            )
            for regiao in dados["regioes"]
        ],
        sem_bairro=[
            (cliente.conta, cliente.nome, cliente.cidade or "—")
            for regiao in dados["regioes"]
            if not regiao.tem_bairro
            for cliente in regiao.clientes
        ],
    )
    return send_file(caminho, as_attachment=True, download_name=caminho.name)
