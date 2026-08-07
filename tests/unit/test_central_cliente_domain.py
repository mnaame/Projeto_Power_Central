import re

from app.domain.central_cliente import elegivel_automatico, gerar_identificador, montar_url

# Formato confirmado contra um link real (docs/CENTRAL_CLIENTE.md §6): 8
# grupos hex separados por hífen, tamanhos 8-4-4-4-13 — NÃO é UUID padrão
# (que seria 8-4-4-4-12).
_PADRAO_IDENTIFICADOR = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{13}$")


def test_gerar_identificador_segue_o_formato_confirmado():
    identificador = gerar_identificador()
    assert _PADRAO_IDENTIFICADOR.match(identificador), identificador


def test_gerar_identificador_e_diferente_a_cada_chamada():
    assert gerar_identificador() != gerar_identificador()


def test_montar_url_usa_a_base_correta():
    url = montar_url("abc-123")
    assert url == "https://novomillenium.auvo.com.br/share/abc-123"


def test_elegivel_automatico_ok_com_score_alto():
    assert elegivel_automatico("OK", 0.95, score_minimo=0.70) is True


def test_elegivel_automatico_ok_com_score_no_limite():
    assert elegivel_automatico("OK", 0.70, score_minimo=0.70) is True


def test_elegivel_automatico_ok_com_score_baixo():
    assert elegivel_automatico("OK", 0.50, score_minimo=0.70) is False


def test_elegivel_automatico_sem_score_nao_passa():
    assert elegivel_automatico("OK", None, score_minimo=0.70) is False


def test_elegivel_automatico_revisar_nao_passa():
    assert elegivel_automatico("REVISAR", 0.95, score_minimo=0.70) is False


def test_elegivel_automatico_nao_nao_passa():
    assert elegivel_automatico("NAO", 0.95, score_minimo=0.70) is False
