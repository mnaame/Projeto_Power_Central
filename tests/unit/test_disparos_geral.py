from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.domain.disparos_geral import (
    GRUPO_BASE,
    GRUPO_SUPER_NOSSO,
    GRUPO_VILLEFORT,
    classificar_conta,
    consolidar,
    grupo_do_cliente,
    texto_ocorrencia,
)

FUSO = ZoneInfo("America/Sao_Paulo")
BASE = datetime(2026, 7, 25, 22, 0, 0, tzinfo=FUSO)


def _fmt(dt):
    return dt.strftime("%m/%d/%Y %I:%M:%S %p")


def _evento(codigo, quando, conta="9385", zona="(28) IVP ENTRADA RM", operador="7",
            rec_iid="100", nome="CLIENTE X", numero="0004"):
    return {
        "rec_iid": rec_iid,
        "rec_iidcuenta": conta,
        "cue_ncuenta": numero,
        "cue_cnombre": nome,
        "rec_calarma": codigo,
        "rec_tfechahora": _fmt(quando),
        "_zon_cdescripcion": zona,
        "rec_ioperador": operador,
    }


# ---------- texto_ocorrencia (redação validada) ----------


def test_ocorrencia_uma_categoria():
    assert texto_ocorrencia({"arme"}, 3, 50) == "DISPARO APÓS ARME"
    assert texto_ocorrencia({"desarme"}, 3, 50) == "DISPARO SEGUIDO DE DESARME"
    assert texto_ocorrencia({"aleatorio"}, 3, 50) == "ALEATORIO"  # sem prefixo


def test_ocorrencia_duas_categorias():
    assert texto_ocorrencia({"arme", "desarme"}, 3, 50) == (
        "DISPAROS APÓS ARME E SEGUIDO DE DESARME"
    )
    assert texto_ocorrencia({"aleatorio", "arme"}, 3, 50) == (
        "DISPAROS APÓS ARME E ALEATORIO"  # ordem fixa: arme, aleatorio, desarme
    )


def test_ocorrencia_tres_categorias():
    assert texto_ocorrencia({"arme", "aleatorio", "desarme"}, 3, 50) == (
        "DISPAROS APÓS ARME, ALEATORIO E SEGUIDO DE DESARME"
    )


def test_ocorrencia_recorrente_acima_do_limite():
    assert texto_ocorrencia({"aleatorio"}, 51, 50) == "RECORRENTE"
    assert texto_ocorrencia({"arme"}, 50, 50) == "DISPARO APÓS ARME"  # 50 não é > 50


# ---------- grupos ----------


def test_grupos_por_nome():
    assert grupo_do_cliente("VILLEFORT SABARÁ") == GRUPO_VILLEFORT
    assert grupo_do_cliente("SUPER NOSSO CASTELO") == GRUPO_SUPER_NOSSO
    assert grupo_do_cliente("APOIO CURVELO FILIAL 529") == GRUPO_SUPER_NOSSO  # APOIO junto
    assert grupo_do_cliente("PET PARA PETS") == GRUPO_BASE
    assert grupo_do_cliente("villefort betânia") == GRUPO_VILLEFORT  # sem acento/case


# ---------- classificação ----------


def test_conta_todos_os_disparos_com_dedup():
    eventos = [
        _evento("BUR", BASE, rec_iid="1"),
        _evento("BUR", BASE, rec_iid="1"),  # repetido -> não conta 2x
        _evento("BUR", BASE + timedelta(hours=1), rec_iid="2"),
    ]
    qtd, _, _, _ = classificar_conta(eventos)
    assert qtd == 2


def test_classifica_apos_arme_seguido_de_desarme_e_aleatorio():
    eventos = [
        _evento("CLO", BASE),  # arme
        _evento("BUR", BASE + timedelta(minutes=2), rec_iid="1"),   # após arme
        _evento("BUR", BASE + timedelta(minutes=30), rec_iid="2"),  # aleatorio
        _evento("BUR", BASE + timedelta(minutes=59, seconds=50), rec_iid="3"),  # antes desarme
        _evento("OPN", BASE + timedelta(hours=1)),  # desarme
    ]
    qtd, texto, _, _ = classificar_conta(eventos)
    assert qtd == 3
    assert texto == "DISPAROS APÓS ARME, ALEATORIO E SEGUIDO DE DESARME"


def test_rcl_conta_como_desarme():
    eventos = [
        _evento("BUR", BASE, rec_iid="1"),  # 10s antes do RCL
        _evento("RCL", BASE + timedelta(seconds=10)),
    ]
    qtd, texto, _, _ = classificar_conta(eventos)
    assert qtd == 1
    assert texto == "DISPARO SEGUIDO DE DESARME"


def test_recorrente_quando_passa_do_limite():
    eventos = [_evento("BUR", BASE + timedelta(seconds=i), rec_iid=str(i)) for i in range(6)]
    qtd, texto, _, _ = classificar_conta(eventos, limite_recorrente=5)
    assert qtd == 6
    assert texto == "RECORRENTE"


def test_zonas_distintas():
    eventos = [
        _evento("BUR", BASE, rec_iid="1", zona="(28) IVP ENTRADA"),
        _evento("BUR", BASE + timedelta(minutes=5), rec_iid="2", zona="(28) IVP ENTRADA"),
        _evento("BUR", BASE + timedelta(minutes=6), rec_iid="3", zona="(11) COFRE"),
    ]
    _, _, zonas, _ = classificar_conta(eventos)
    assert zonas == ("(28) IVP ENTRADA", "(11) COFRE")


# ---------- consolidar ----------


def test_consolidar_agrupa_e_ordena():
    eventos = [
        _evento("BUR", BASE, conta="1", nome="VILLEFORT HM", numero="10", rec_iid="a"),
        _evento("BUR", BASE, conta="2", nome="SUPER NOSSO CASTELO", numero="20", rec_iid="b"),
        _evento("BUR", BASE, conta="3", nome="ABC MERCADO", numero="30", rec_iid="c"),
    ]
    clientes = consolidar(eventos)
    assert len(clientes) == 3
    grupos = {c.cliente: c.grupo for c in clientes}
    assert grupos["VILLEFORT HM"] == GRUPO_VILLEFORT
    assert grupos["SUPER NOSSO CASTELO"] == GRUPO_SUPER_NOSSO
    assert grupos["ABC MERCADO"] == GRUPO_BASE
    # ordenado por nome
    assert [c.cliente for c in clientes][0] == "ABC MERCADO"
    # conta_numero veio do cue_ncuenta
    assert next(c for c in clientes if c.cliente == "VILLEFORT HM").conta_numero == "10"
