"""Geometria de gráfico.

Gráfico errado não dá exceção: dá uma barra do tamanho errado, que o
leitor acredita. Daí as contas ficarem fora do template, onde dá para
conferir que a barra de 1,20 é mesmo o dobro da de 0,60.
"""

from app.domain import graficos as dom


def _itens(valores):
    return [(f"c{i}", v, "is-serie", "") for i, v in enumerate(valores)]


# ---------- o eixo ----------


def test_passo_sobe_para_numero_redondo():
    assert dom.passo_bonito(0.3) == 0.5
    assert dom.passo_bonito(0.24) == 0.25
    assert dom.passo_bonito(3.0) == 5.0
    assert dom.passo_bonito(11.0) == 20.0


def test_eixo_nao_desperdica_a_altura_do_grafico():
    """O defeito visto na primeira renderização: máximo 1,20 fechando em
    2,00 jogava fora 40% da altura e achatava todas as barras. Testando
    mais de uma divisão, o mesmo 1,20 fecha em 1,25."""
    escala = dom.eixo(1.20)

    assert escala.maximo == 1.25
    assert escala.maximo < 2.0


def test_eixo_sempre_cobre_o_maior_valor():
    """Teto abaixo do dado desenharia a barra fora do gráfico."""
    for bruto in (0.01, 0.48, 1.2, 7.0, 13.0, 99.0, 1234.0):
        assert dom.eixo(bruto).maximo >= bruto


def test_eixo_comeca_no_zero():
    """Eixo truncado transforma uma diferença de 3% num abismo visual."""
    assert dom.eixo(5.0).valores[0] == 0


def test_eixo_de_tudo_zerado_ainda_e_utilizavel():
    """Nenhum disparo no período é um resultado, não um gráfico
    quebrado."""
    escala = dom.eixo(0.0)

    assert escala.maximo > 0
    assert len(escala.valores) > 1


def test_casas_decimais_saem_do_passo():
    """Com passo 0,25 o eixo precisa de duas casas; fixar uma viraria
    "0,3" — um eixo que mente. Com passo 0,1, duas casas escreveriam
    "0,10 / 0,20", que é ruído."""
    assert dom.eixo(1.20).casas == 2  # passo 0,25
    assert dom.eixo(0.48).casas == 1  # passo 0,1
    assert dom.eixo(40.0).casas == 0


# ---------- a marca ----------


def test_coluna_tem_ponta_arredondada_e_base_quadrada():
    """`rx` arredondaria os quatro cantos, e barra de base redonda
    descola do eixo."""
    caminho = dom.caminho_coluna(10, 20, 24, 80)

    assert caminho.count("Q") == 2  # só os dois cantos de cima
    assert caminho.endswith("Z")
    assert "M 10.0 100.0" in caminho  # sai da base, não do topo


def test_coluna_sem_altura_nao_vira_risco_no_eixo():
    """Valor zero é ausência de barra, não uma barra de 1px — que leria
    como "quase nada" em vez de "nada"."""
    assert dom.caminho_coluna(10, 100, 24, 0) == ""


def test_barra_baixa_nao_estoura_o_arredondamento():
    """Com altura menor que o raio, o arco invadiria a base e a barra
    sairia com formato negativo."""
    caminho = dom.caminho_coluna(0, 98, 24, 2)

    assert caminho and "-" not in caminho


# ---------- o conjunto ----------


def test_altura_da_barra_e_proporcional_ao_valor():
    grafico = dom.montar_colunas(_itens([1.0, 0.5]), largura=300, altura=200)

    alta, baixa = grafico.colunas
    assert round((grafico.base_y - alta.topo_y) / (grafico.base_y - baixa.topo_y), 2) == 2.0


def test_barra_nao_preenche_a_faixa_inteira():
    """Barra ocupando o slot todo vira bloco; o resto da faixa é respiro."""
    grafico = dom.montar_colunas(_itens([1.0, 1.0]), largura=300, altura=200)

    assert grafico.colunas[0].banda_largura > dom.LARGURA_MAXIMA_COLUNA


def test_barra_tem_espessura_maxima():
    """Com duas colunas num gráfico largo, a barra cresceria até virar
    um painel."""
    grafico = dom.montar_colunas(_itens([1.0, 1.0]), largura=900, altura=200)

    caminho = grafico.colunas[0].caminho
    largura = float(caminho.split("H ")[1].split()[0]) - float(caminho.split("M ")[1].split()[0])
    assert largura <= dom.LARGURA_MAXIMA_COLUNA


def test_faixas_de_hover_cobrem_o_grafico_sem_buraco():
    """O alvo do ponteiro é a faixa, não a barra: acertar uma coluna de
    8px no celular é impossível."""
    grafico = dom.montar_colunas(_itens([1, 2, 3, 4]), largura=400, altura=200)

    for anterior, seguinte in zip(grafico.colunas, grafico.colunas[1:]):
        fim = anterior.banda_x + anterior.banda_largura
        assert abs(fim - seguinte.banda_x) < 0.2


def test_rotulo_de_categoria_rareia_quando_sao_muitos():
    """Com 30 semanas os rótulos se encavalam e viram borrão. As barras
    continuam todas; só o texto rareia."""
    grafico = dom.montar_colunas(_itens(range(30)), largura=660, altura=210)

    mostrados = sum(1 for c in grafico.colunas if c.mostrar_rotulo)
    assert len(grafico.colunas) == 30
    assert 1 < mostrados <= 10


def test_poucas_colunas_mostram_todos_os_rotulos():
    grafico = dom.montar_colunas(_itens([1, 2]), largura=300, altura=200)

    assert all(c.mostrar_rotulo for c in grafico.colunas)


def test_grafico_sem_itens_nao_quebra():
    grafico = dom.montar_colunas([], largura=300, altura=200)

    assert grafico.colunas == [] and grafico.marcas == []


def test_classe_da_coluna_e_preservada():
    """A cor é função (neutro/melhora/piora), e quem decide é a camada de
    cima — não o desenhista."""
    grafico = dom.montar_colunas(
        [("Antes", 1.0, "is-neutro", ""), ("Depois", 0.5, "is-melhora", "")],
        largura=300, altura=200,
    )

    assert [c.classe for c in grafico.colunas] == ["is-neutro", "is-melhora"]


# ---------- formatação ----------


def test_numero_sai_com_virgula_decimal():
    assert dom.formatar_numero(0.89) == "0,89"
    assert dom.formatar_numero(1.0, 0) == "1"
