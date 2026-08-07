import uuid

from app.domain.central_cliente import elegivel_automatico, gerar_identificador, montar_url


def test_gerar_identificador_e_uuid_valido():
    identificador = gerar_identificador()
    # Levanta ValueError se não for um UUID válido.
    uuid.UUID(identificador)


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
