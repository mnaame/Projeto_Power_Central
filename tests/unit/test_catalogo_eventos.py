from app.domain import catalogo_eventos as dom


def test_descricao_conhecida_vira_codigo():
    """Linha real da conta 118: o export guarda só a descrição."""
    assert dom.codigo_da_descricao(
        "Falha no Teste Periódico de Comunicação (Painel de Alarme Off-Line)"
    ) == "NYR"


def test_acento_e_caixa_nao_atrapalham():
    assert dom.codigo_da_descricao("FALHA NO TESTE PERIODICO DE COMUNICACAO "
                                   "(PAINEL DE ALARME OFF-LINE)") == "NYR"


def test_espacos_sobrando_sao_colapsados():
    assert dom.codigo_da_descricao("  Alarme   Armado  ") == "CLO"


def test_descricao_desconhecida_devolve_vazio_em_vez_de_chutar():
    assert dom.codigo_da_descricao("Evento que ninguém mapeou ainda") == ""


def test_codigo_embutido_no_texto_e_aproveitado():
    """Se algum dia o export passar a trazer "NYR - ...", aproveitamos sem
    depender do mapa."""
    assert dom.codigo_da_descricao("BUR - Disparo de zona") == "BUR"


def test_restauracao_nao_casa_com_o_proprio_problema():
    """"Restauração de Disparo" contém "Disparo": casar por pedaço faria a
    volta ao normal inflar a contagem do problema."""
    assert dom.codigo_da_descricao("Restauração de Disparo") == "RES"
    assert dom.codigo_da_descricao("Restauração de Disparo") != "BUR"


def test_mapa_da_configuracao_e_lido():
    mapa = dom.mapa_de_texto("Disparo de Zona=BUR\nZona Isolada=BYP")

    assert dom.codigo_da_descricao("disparo de zona", mapa=mapa) == "BUR"
    assert dom.codigo_da_descricao("Zona Isolada", mapa=mapa) == "BYP"


def test_linha_malformada_na_configuracao_e_ignorada():
    """Config com erro de digitação não pode derrubar o diagnóstico."""
    mapa = dom.mapa_de_texto("sem sinal de igual\nDisparo=BUR\n=SEMDESCRICAO\n")

    assert mapa == {"disparo": "BUR"}
