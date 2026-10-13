"""Rotas de visita preventiva — tela, mapa e export.

O resultado fica em `session` entre o "gerar" e o "exportar" pelo mesmo
motivo do resto do sistema: a geração consulta duas plataformas e leva
tempo. Guardando, o export e o mapa reusam o que já foi calculado em vez
de refazer tudo — e, principalmente, exportam **exatamente** o que está
na tela.
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

from app.extensions import db
from app.integrations.softguard_client import SoftGuardError
from app.services import rotas_service, settings_service
from app.services.report_xlsx import gerar_xlsx_rotas

bp = Blueprint("rotas", __name__, url_prefix="/rotas")

CHAVE_SESSAO = "rotas_resultado"


def _serializar(resultado: dict) -> dict:
    """Formato leve para a sessão e para o mapa — dataclass não vai para
    JSON, e o template do mapa precisa de dict mesmo."""
    return {
        "resumo": resultado["resumo"],
        "sem_coord": resultado["sem_coord"],
        "rotas": [
            {
                "indice": rota.indice,
                "tamanho": rota.tamanho,
                "cidades": rota.cidades,
                "extensao_km": rota.extensao_km,
                "pontos": [
                    {
                        "ordem": ordem,
                        "conta": p.conta,
                        "nome": p.nome,
                        "cidade": p.cidade,
                        "lat": p.lat,
                        "lon": p.lon,
                        "fonte": p.fonte,
                    }
                    for ordem, p in enumerate(rota.pontos, start=1)
                ],
            }
            for rota in resultado["rotas"]
        ],
    }


@bp.route("")
@login_required
def index():
    return render_template(
        "rotas/index.html",
        resultado=session.get(CHAVE_SESSAO),
        raio_km=settings_service.get_rotas_raio_km(),
    )


@bp.route("/gerar", methods=["POST"])
@login_required
def gerar():
    # `or` aqui seria armadilha: 0 é falsy e viraria o padrão em silêncio,
    # entregando um raio diferente do que foi digitado. O padrão só vale
    # quando o campo não veio.
    informado = request.form.get("raio_km", type=float)
    raio = settings_service.get_rotas_raio_km() if informado is None else informado
    if raio <= 0:
        flash("O raio precisa ser maior que zero.", "warning")
        return redirect(url_for("rotas.index"))

    try:
        resultado = rotas_service.montar_rotas(
            config=current_app.config, raio_km=raio, user=current_user
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
            f"Coordenadas da Auvo indisponíveis ({resumo['erro_auvo']}) — "
            "usei só a localização da PowerCentral, então pode faltar cliente.",
            "warning",
        )
    flash(
        f"{resumo['clusters']} rota(s) com {resumo['com_coord']} cliente(s) "
        f"a {raio} km. {resumo['sem_coord']} sem coordenada.",
        "info",
    )
    return redirect(url_for("rotas.index"))


@bp.route("/exportar")
@login_required
def exportar():
    resultado = session.get(CHAVE_SESSAO)
    if not resultado:
        flash("Gere as rotas antes de exportar.", "warning")
        return redirect(url_for("rotas.index"))

    pasta = Path(current_app.instance_path) / "reports" / "rotas"
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    caminho = pasta / f"rotas_{carimbo}.xlsx"

    gerar_xlsx_rotas(
        caminho,
        clientes=[
            (
                rota["indice"], ponto["ordem"], ponto["conta"], ponto["nome"],
                ponto["cidade"], ponto["lat"], ponto["lon"], ponto["fonte"],
            )
            for rota in resultado["rotas"]
            for ponto in rota["pontos"]
        ],
        resumo=[
            (r["indice"], r["tamanho"], r["cidades"], r["extensao_km"])
            for r in resultado["rotas"]
        ],
        sem_coordenada=[
            (s["conta"], s["nome"], s["cidade"], s["motivo"])
            for s in resultado["sem_coord"]
        ],
    )
    return send_file(caminho, as_attachment=True, download_name=caminho.name)
