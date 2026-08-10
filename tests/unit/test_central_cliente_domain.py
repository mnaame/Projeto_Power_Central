import re

from app.domain.central_cliente import (
    elegivel_automatico,
    gerar_identificador,
    montar_link_whatsapp,
    montar_url,
    normalizar_telefone,
)

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


# ---------- normalizar_telefone ----------


def test_normalizar_telefone_ja_com_ddi():
    assert normalizar_telefone("5531999998888") == "5531999998888"


def test_normalizar_telefone_com_formatacao_e_sem_ddi():
    assert normalizar_telefone("(31) 99999-8888") == "5531999998888"


def test_normalizar_telefone_com_mais_e_espacos():
    assert normalizar_telefone("+55 31 99999-8888") == "5531999998888"


def test_normalizar_telefone_fixo_sem_nono_digito():
    assert normalizar_telefone("31 3333-4444") == "553133334444"


def test_normalizar_telefone_none_para_vazio():
    assert normalizar_telefone("") is None
    assert normalizar_telefone(None) is None


def test_normalizar_telefone_none_para_muito_curto():
    assert normalizar_telefone("999") is None


def test_normalizar_telefone_none_para_ddd_sem_ddi_ambiguo_com_ddi():
    # DDD 55 (Santa Maria) sem DDI é ambíguo com o próprio DDI 55 — o
    # resultado não bate 12/13 dígitos, então fica de fora por segurança
    # em vez de arriscar abrir no contato errado.
    assert normalizar_telefone("55999998888") is None


# ---------- montar_link_whatsapp ----------


def test_montar_link_whatsapp_urlencoda_a_mensagem():
    link = montar_link_whatsapp("5531999998888", "Olá! Tudo bem?")
    assert link.startswith("https://wa.me/5531999998888?text=")
    assert "Ol%C3%A1" in link or "Ola" in link
    assert " " not in link
