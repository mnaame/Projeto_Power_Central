from app.domain import rotas as dom

# Pontos reais de BH para a geometria não ser testada só contra si mesma.
PRACA_SETE = (-19.9191, -43.9386)
SAVASSI = (-19.9380, -43.9330)  # ~2,3 km da Praça Sete
CONTAGEM = (-19.9320, -44.0540)  # ~12 km


def _ponto(conta, lat, lon, nome=None, cidade="BELO HORIZONTE"):
    return dom.PontoCliente(
        conta=conta, nome=nome or f"CLIENTE {conta}", cidade=cidade,
        lat=lat, lon=lon, fonte=dom.FONTE_AUVO,
    )


# ---------- distância ----------


def test_distancia_de_um_ponto_a_ele_mesmo_e_zero():
    assert dom.distancia_km(*PRACA_SETE, *PRACA_SETE) == 0


def test_distancia_conhecida_entre_dois_pontos_de_bh():
    distancia = dom.distancia_km(*PRACA_SETE, *SAVASSI)

    assert 2.0 < distancia < 2.7  # ~2,3 km em linha reta


def test_distancia_e_simetrica():
    assert dom.distancia_km(*PRACA_SETE, *CONTAGEM) == dom.distancia_km(*CONTAGEM, *PRACA_SETE)


# ---------- validação de coordenada ----------


def test_coordenada_de_bh_e_aceita():
    assert dom.coordenada_valida(-19.9191, -43.9386) == (-19.9191, -43.9386)


def test_coordenada_de_outro_estado_e_descartada():
    """Uma coordenada errada não atrapalha só a si: entra num cluster e
    puxa o centroide da rota inteira para o lugar errado."""
    assert dom.coordenada_valida(-23.5505, -46.6333) is None  # São Paulo


def test_ilha_nula_e_descartada():
    """(0,0) é o que um cadastro vazio vira — fica no Atlântico."""
    assert dom.coordenada_valida(0, 0) is None


def test_coordenada_ausente_ou_ilegivel():
    assert dom.coordenada_valida(None, None) is None
    assert dom.coordenada_valida("", "") is None
    assert dom.coordenada_valida("abc", "def") is None


def test_coordenada_com_virgula_decimal_e_aceita():
    assert dom.coordenada_valida("-19,9191", "-43,9386") == (-19.9191, -43.9386)


def test_localizacao_da_power_no_formato_lat_virgula_long():
    assert dom.coordenada_de_texto("-19.9191,-43.9386") == (-19.9191, -43.9386)
    assert dom.coordenada_de_texto("-19.9191, -43.9386") == (-19.9191, -43.9386)


def test_localizacao_da_power_fora_da_regiao_e_descartada():
    assert dom.coordenada_de_texto("-23.5505,-46.6333") is None


def test_localizacao_sem_virgula_nao_e_coordenada():
    assert dom.coordenada_de_texto("centro") is None
    assert dom.coordenada_de_texto("") is None


def test_virgula_como_decimal_E_separador():
    """`-19,9191,-43,9386` — a vírgula nos dois papéis. O `partition(",")`
    da primeira versão lia isso como lat="-19" e long="9191,-43,9386"."""
    assert dom.coordenada_de_texto("-19,9191,-43,9386") == (-19.9191, -43.9386)


def test_texto_com_um_numero_so_ou_com_tres_nao_e_coordenada():
    """Exatamente dois decimais. Um endereço com número e um CEP juntos
    não podem virar coordenada por acidente."""
    assert dom.coordenada_de_texto("-19.9191") is None
    assert dom.coordenada_de_texto("-19.9191,-43.9386,120.5") is None


# ---------- achar a coordenada sem saber o nome do campo ----------
#
# Chutar nome de campo custou 105 contas sem coordenada numa rodada
# inteira — zero, sem um erro na tela. Agora a coordenada é reconhecida
# pela forma.


def test_registro_com_latitude_e_longitude():
    assert dom.coordenada_do_registro(
        {"id": 1, "latitude": -19.9191, "longitude": -43.9386}
    ) == (-19.9191, -43.9386)


def test_registro_com_nomes_em_caixa_alta_e_virgula_decimal():
    """É o formato que o export da Auvo entrega: `-19,8435179`."""
    assert dom.coordenada_do_registro(
        {"Latitude": "-19,9191", "Longitude": "-43,9386"}
    ) == (-19.9191, -43.9386)


def test_registro_com_lat_lng_abreviados():
    assert dom.coordenada_do_registro({"lat": -19.9191, "lng": -43.9386}) == (
        -19.9191,
        -43.9386,
    )


def test_registro_com_lat_long_zeradas_nao_tem_coordenada():
    """Grande parte do cadastro da Auvo está com 0/0 — é cadastro vazio,
    não é a ilha nula do Atlântico."""
    assert dom.coordenada_do_registro({"latitude": "0", "longitude": "0"}) is None


def test_coordenada_e_achada_em_campo_de_nome_desconhecido():
    """O ponto do módulo: o campo da "Localização da conta" da
    PowerCentral pode se chamar qualquer coisa."""
    assert dom.coordenada_do_registro(
        {"cue_cnombre": "PADARIA DO ZE", "campo_qualquer": "-19.9191,-43.9386"}
    ) == (-19.9191, -43.9386)


def test_coordenada_e_achada_em_sub_registro():
    assert dom.coordenada_do_registro(
        {"id": 1, "address": {"latitude": "-19.9191", "longitude": "-43.9386"}}
    ) == (-19.9191, -43.9386)


def test_endereco_e_telefone_nao_viram_coordenada():
    """A caixa da região é o que impede um par de números qualquer de
    passar por coordenada."""
    assert (
        dom.coordenada_do_registro(
            {
                "rua": "AV. AFONSO PENA, 1.500",
                "cep": "30.130-110",
                "telefone": "(31) 3333-4444",
                "valor": "1.234,56",
            }
        )
        is None
    )


def test_coordenada_de_fora_da_regiao_no_registro_e_descartada():
    """Boa parte da "Localização da conta" aponta para outro estado."""
    assert dom.coordenada_do_registro({"loc": "-23.9500,-46.2700"}) is None


def test_registro_que_nao_e_dicionario():
    assert dom.coordenada_do_registro(None) is None
    assert dom.coordenada_do_registro("-19.9191,-43.9386") is None


# ---------- agrupamento ----------


def test_pontos_proximos_ficam_na_mesma_rota():
    rotas = dom.agrupar([_ponto("1", *PRACA_SETE), _ponto("2", *SAVASSI)], raio_km=3.0)

    assert len(rotas) == 1
    assert rotas[0].tamanho == 2


def test_pontos_distantes_ficam_em_rotas_separadas():
    rotas = dom.agrupar([_ponto("1", *PRACA_SETE), _ponto("2", *CONTAGEM)], raio_km=3.0)

    assert len(rotas) == 2


def test_proximidade_e_transitiva():
    """A perto de B, B perto de C ⇒ os três na mesma rota, mesmo com A e C
    longe. É o comportamento certo para clientes enfileirados ao longo de
    uma avenida."""
    a = _ponto("1", -19.9191, -43.9386)
    b = _ponto("2", -19.9280, -43.9386)  # ~1 km de A
    c = _ponto("3", -19.9370, -43.9386)  # ~1 km de B, ~2 km de A

    rotas = dom.agrupar([a, b, c], raio_km=1.3)

    assert len(rotas) == 1
    assert rotas[0].tamanho == 3


def test_raio_maior_junta_o_que_estava_separado():
    pontos = [_ponto("1", *PRACA_SETE), _ponto("2", *CONTAGEM)]

    assert len(dom.agrupar(pontos, raio_km=3.0)) == 2
    assert len(dom.agrupar(pontos, raio_km=20.0)) == 1


def test_rotas_saem_da_maior_para_a_menor():
    pontos = [
        _ponto("9", *CONTAGEM),
        _ponto("1", *PRACA_SETE),
        _ponto("2", -19.9200, -43.9390),
        _ponto("3", -19.9195, -43.9380),
    ]

    rotas = dom.agrupar(pontos, raio_km=1.0)

    assert [r.tamanho for r in rotas] == [3, 1]
    assert rotas[0].indice == 1


def test_mesmo_conjunto_gera_sempre_o_mesmo_resultado():
    """Rodar duas vezes com os mesmos dados tem que dar a mesma resposta —
    senão a equipe não consegue conferir nada."""
    pontos = [_ponto(str(i), -19.9191 - i / 1000, -43.9386) for i in range(6)]

    primeira = dom.agrupar(pontos, raio_km=1.0)
    segunda = dom.agrupar(list(reversed(pontos)), raio_km=1.0)

    assert [[p.conta for p in r.pontos] for r in primeira] == \
           [[p.conta for p in r.pontos] for r in segunda]


def test_rota_de_dois_clientes_tambem_sai_sempre_na_mesma_ordem():
    """Regressão: `ordenar_visita` devolvia uma dupla na ordem em que ela
    chegou, e com a base real isso fez quatro rotas de dois clientes
    saírem invertidas conforme a ordem da plataforma."""
    a = _ponto("0101", -19.9191, -43.9386)
    b = _ponto("0108", -19.9195, -43.9380)

    assert [p.conta for p in dom.ordenar_visita([a, b])] == \
           [p.conta for p in dom.ordenar_visita([b, a])]


def test_centroide_nao_depende_da_ordem_das_parcelas():
    """Soma de float depende da ordem; a mesma rota em outra ordem dava um
    centroide diferente nos últimos bits, o bastante para trocar o ponto
    de partida num empate apertado."""
    pontos = [_ponto(str(i), -19.9191 + i / 97, -43.9386 - i / 89) for i in range(12)]

    assert dom.centroide(pontos) == dom.centroide(list(reversed(pontos)))


def test_lista_vazia_nao_gera_rota():
    assert dom.agrupar([], raio_km=1.5) == []


# ---------- ordem de visita ----------


def test_ordem_evita_zigue_zague():
    """Em fila, a ordem tem que percorrer a fila — não pular de ponta a
    ponta como faria a ordem alfabética."""
    pontos = [
        _ponto("Z", -19.9191, -43.9386),
        _ponto("A", -19.9400, -43.9386),
        _ponto("M", -19.9290, -43.9386),
    ]

    ordem = [p.conta for p in dom.ordenar_visita(pontos)]

    assert ordem in (["M", "Z", "A"], ["M", "A", "Z"])  # começa pelo centro
    assert ordem.index("M") == 0


def test_extensao_soma_as_pernas_da_rota():
    rota = dom.agrupar([_ponto("1", *PRACA_SETE), _ponto("2", *SAVASSI)], raio_km=5.0)[0]

    assert 2.0 < rota.extensao_km < 2.7


def test_rota_de_um_ponto_nao_tem_percurso():
    rota = dom.agrupar([_ponto("1", *PRACA_SETE)], raio_km=1.5)[0]

    assert rota.extensao_km == 0


def test_cidades_da_rota_sem_repetir():
    rota = dom.agrupar(
        [
            _ponto("1", *PRACA_SETE, cidade="BELO HORIZONTE"),
            _ponto("2", -19.9195, -43.9380, cidade="BELO HORIZONTE"),
        ],
        raio_km=5.0,
    )[0]

    assert rota.cidades == "BELO HORIZONTE"


# ---------- nomes ----------


def test_nome_igual_com_acento_e_caixa_diferentes_casa():
    assert dom.melhor_nome("Padaria Sao Joao", ["PADARIA SÃO JOÃO"]) == "PADARIA SÃO JOÃO"


def test_nome_parecido_demais_mas_nao_igual_nao_casa():
    """Ligar o cliente errado a uma coordenada manda o técnico para o
    endereço de outra pessoa — o corte é alto de propósito."""
    assert dom.melhor_nome("PADARIA CENTRO", ["PADARIA CENTRO SUL LTDA ME"]) == ""


def test_interno_e_reconhecido():
    assert dom.e_interno("NOVO MILLENIUM") is True
    assert dom.e_interno("CONTA TESTE ITALO") is True
    assert dom.e_interno("PADARIA DO ZE") is False
