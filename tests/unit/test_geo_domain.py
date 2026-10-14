"""Coordenadas: reconhecer, validar e medir.

Este código veio do agrupamento por km, que foi substituído pelo catálogo
por bairro. Ele continua valendo por outro motivo: é a coordenada que
coloca o cliente no mapa — e uma coordenada errada no mapa é um cliente
plantado a 400 km de onde ele está.
"""

from app.domain import geo

PRACA_SETE = (-19.9191, -43.9386)
SAVASSI = (-19.9380, -43.9330)  # ~2,3 km da Praça Sete


# ---------- validação ----------


def test_coordenada_de_bh_e_aceita():
    assert geo.coordenada_valida(-19.9191, -43.9386) == PRACA_SETE


def test_coordenada_de_outro_estado_e_descartada():
    """Na base real, 13 das 104 contas com coordenada apontavam para o
    interior de São Paulo."""
    assert geo.coordenada_valida(-23.5505, -46.6333) is None


def test_ilha_nula_e_descartada():
    """(0,0) é o que um cadastro vazio vira — fica no Atlântico."""
    assert geo.coordenada_valida(0, 0) is None
    assert geo.coordenada_valida("0", "0") is None


def test_coordenada_ausente_ou_ilegivel():
    assert geo.coordenada_valida(None, None) is None
    assert geo.coordenada_valida("", "") is None
    assert geo.coordenada_valida("abc", "def") is None


def test_virgula_decimal_e_aceita():
    """É como o export da Auvo entrega: `-19,8435179`."""
    assert geo.coordenada_valida("-19,9191", "-43,9386") == PRACA_SETE


# ---------- par num campo só ----------


def test_par_lat_virgula_long():
    """A "Localização da conta" da PowerCentral."""
    assert geo.coordenada_de_texto("-19.9191,-43.9386") == PRACA_SETE
    assert geo.coordenada_de_texto("-19.9191, -43.9386") == PRACA_SETE


def test_virgula_como_decimal_E_separador():
    assert geo.coordenada_de_texto("-19,9191,-43,9386") == PRACA_SETE


def test_texto_que_nao_e_coordenada():
    assert geo.coordenada_de_texto("centro") is None
    assert geo.coordenada_de_texto("") is None
    assert geo.coordenada_de_texto("-19.9191") is None  # só um número


# ---------- achar sem saber o nome do campo ----------


def test_registro_com_latitude_e_longitude():
    assert geo.coordenada_do_registro(
        {"id": 1, "latitude": -19.9191, "longitude": -43.9386}
    ) == PRACA_SETE


def test_coordenada_em_campo_de_nome_desconhecido():
    """Chutar nome de campo já custou 105 contas sem coordenada numa
    rodada inteira — zero, sem um erro na tela."""
    assert geo.coordenada_do_registro(
        {"nome": "PADARIA", "campo_qualquer": "-19.9191,-43.9386"}
    ) == PRACA_SETE


def test_endereco_e_cep_nao_viram_coordenada():
    assert (
        geo.coordenada_do_registro(
            {"rua": "AV. AFONSO PENA, 1.500", "cep": "30.130-110", "valor": "1.234,56"}
        )
        is None
    )


# ---------- distância ----------


def test_distancia_conhecida_entre_dois_pontos_de_bh():
    assert 2.0 < geo.distancia_km(*PRACA_SETE, *SAVASSI) < 2.7


def test_distancia_e_simetrica():
    assert geo.distancia_km(*PRACA_SETE, *SAVASSI) == geo.distancia_km(*SAVASSI, *PRACA_SETE)
