"""Agrupamento dos clientes base por bairro."""

from app.domain import rotas as dom


def _cliente(conta, nome=None, bairro="", cidade="BELO HORIZONTE"):
    return dom.ClienteBase(
        conta=conta, nome=nome or f"CLIENTE {conta}", bairro=bairro, cidade=cidade
    )


# ---------- agrupamento ----------


def test_mesmo_bairro_e_mesma_cidade_viram_uma_regiao():
    regioes = dom.agrupar_por_regiao(
        [_cliente("1", bairro="Buritis"), _cliente("2", bairro="Buritis")]
    )

    assert len(regioes) == 1
    assert regioes[0].tamanho == 2


def test_bairro_escrito_em_caixas_diferentes_e_a_mesma_regiao():
    """"ESTORIL" e "Estoril" convivem no cadastro real. Duas regiões =
    duas saídas para o mesmo lugar."""
    regioes = dom.agrupar_por_regiao(
        [_cliente("1", bairro="ESTORIL"), _cliente("2", bairro="Estoril")]
    )

    assert len(regioes) == 1
    assert regioes[0].rotulo == "Estoril — Belo Horizonte"


def test_bairro_de_mesmo_nome_em_cidade_diferente_nao_se_mistura():
    """"Centro" de BH e "Centro" de Contagem estão a trinta quilômetros —
    juntá-los é o erro mais caro que este módulo poderia cometer."""
    regioes = dom.agrupar_por_regiao(
        [
            _cliente("1", bairro="Centro", cidade="Belo Horizonte"),
            _cliente("2", bairro="Centro", cidade="Contagem"),
        ]
    )

    assert len(regioes) == 2


def test_regioes_maiores_primeiro():
    """É a ordem em que a operação decide o que fazer: a região com mais
    clientes rende mais numa saída só."""
    regioes = dom.agrupar_por_regiao(
        [
            _cliente("1", bairro="Savassi"),
            _cliente("2", bairro="Buritis"),
            _cliente("3", bairro="Buritis"),
        ]
    )

    assert [r.tamanho for r in regioes] == [2, 1]
    assert regioes[0].rotulo.startswith("Buritis")


def test_quem_nao_tem_bairro_fica_por_ultimo_e_agrupado_pela_cidade():
    """Não some: some seria pior, porque ninguém procura o que não
    aparece. Vai para o fim porque não é uma visita, é uma pendência de
    cadastro."""
    regioes = dom.agrupar_por_regiao(
        [
            _cliente("1", cidade="Belo Horizonte"),
            _cliente("2", cidade="Belo Horizonte"),
            _cliente("3", cidade="Belo Horizonte"),
            _cliente("4", bairro="Savassi"),
        ]
    )

    assert regioes[0].rotulo == "Savassi — Belo Horizonte"
    assert regioes[-1].rotulo == "(sem bairro) — Belo Horizonte"
    assert regioes[-1].tamanho == 3
    assert regioes[-1].tem_bairro is False


def test_quem_nao_tem_nem_cidade_tambem_aparece():
    regioes = dom.agrupar_por_regiao([_cliente("1", cidade="")])

    assert regioes[0].rotulo == dom.ROTULO_SEM_REGIAO


def test_mesma_entrada_em_outra_ordem_da_o_mesmo_resultado():
    """Rodar duas vezes com os mesmos dados tem que dar a mesma resposta —
    senão a equipe não consegue conferir nada."""
    clientes = [
        _cliente("3", bairro="Buritis"),
        _cliente("1", bairro="Savassi"),
        _cliente("2", bairro="Buritis"),
        _cliente("4", cidade="Contagem"),
    ]

    primeira = dom.agrupar_por_regiao(clientes)
    segunda = dom.agrupar_por_regiao(list(reversed(clientes)))

    assert [(r.rotulo, [c.conta for c in r.clientes]) for r in primeira] == \
           [(r.rotulo, [c.conta for c in r.clientes]) for r in segunda]


def test_clientes_da_regiao_saem_por_numero_de_conta():
    regiao = dom.agrupar_por_regiao(
        [_cliente("0120", bairro="Centro"), _cliente("0007", bairro="Centro")]
    )[0]

    assert [c.conta for c in regiao.clientes] == ["0007", "0120"]


def test_lista_vazia_nao_gera_regiao():
    assert dom.agrupar_por_regiao([]) == []


# ---------- nomes ----------


def test_nome_igual_com_acento_e_caixa_diferentes_casa():
    assert dom.melhor_nome("Padaria Sao Joao", ["PADARIA SÃO JOÃO"]) == "PADARIA SÃO JOÃO"


def test_nome_parecido_demais_mas_nao_igual_nao_casa():
    """Ligar o cliente errado a um endereço manda o técnico para a região
    de outra pessoa — o corte é alto de propósito."""
    assert dom.melhor_nome("PADARIA CENTRO", ["PADARIA CENTRO SUL LTDA ME"]) == ""


def test_interno_e_reconhecido():
    assert dom.e_interno("NOVO MILLENIUM") is True
    assert dom.e_interno("CONTA TESTE ITALO") is True
    assert dom.e_interno("PADARIA DO ZE") is False
