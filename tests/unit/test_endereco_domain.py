"""Leitura de bairro e cidade de endereço escrito por gente.

Todos os endereços daqui são **reais**, copiados do cadastro da Auvo. O
risco deste módulo não é falhar em ler — é ler errado e colocar o cliente
num bairro que não é o dele, o que manda o técnico para a região errada
sem ninguém desconfiar.
"""

from app.domain import endereco as end


# ---------- a forma canônica ----------


def test_endereco_completo_separado_por_virgula():
    e = end.ler("Rua João Monlevade,109,,Jardim Leblon,Belo Horizonte,MG,31540280")

    assert e.bairro == "Jardim Leblon"
    assert e.cidade == "Belo Horizonte"
    assert e.uf == "MG"
    assert e.cep == "31540280"


def test_cep_com_ponto_e_hifen():
    e = end.ler("RUA SEBASTIAO POSSADA BRAVO,30,LETRA A,SANTA ROSA,Belo Horizonte,MG,31.255-760")

    assert e.bairro == "SANTA ROSA"
    assert e.cep == "31255-760"


# ---------- as variações que convivem no mesmo cadastro ----------


def test_cidade_e_uf_coladas_com_hifen():
    e = end.ler("R. Plutão, 144 - Santa Lúcia, Belo Horizonte - MG, 30360-450")

    assert e.bairro == "Santa Lúcia"
    assert e.cidade == "Belo Horizonte"


def test_numero_colado_no_bairro_e_descartado():
    """"690 - Castelo" é número e bairro no mesmo pedaço."""
    assert end.ler(
        "Av. Altamiro Avelino Soares, 690 - Castelo, Belo Horizonte - MG, 31330-000"
    ).bairro == "Castelo"


def test_pais_no_fim_nao_atrapalha():
    e = end.ler("Rua Miranda Ribeiro, 225, Vila Paris, Belo Horizonte - MG, 30380-660, Brasil")

    assert e.bairro == "Vila Paris"
    assert e.cidade == "Belo Horizonte"


def test_pais_com_tipo_de_imovel_pendurado():
    """Alguém escreveu "Brasil - escola" no fim. Sem tratar, "Brasil -
    escola" virava o nome do bairro."""
    assert end.ler(
        "Rua Benjamim Quadros, 255, Paraíso, Belo Horizonte - MG, 30270-130, Brasil - escola"
    ).bairro == "Paraíso"


def test_bairro_que_tem_hifen_no_proprio_nome_fica_inteiro():
    """"Palmares - 4ª Seção" é UM bairro. Quebrar no hífen cortava o nome
    ao meio e inventava uma região que não existe."""
    e = end.ler(
        "Rua Rio Grande,281,CASA4,Palmares - 4ª Seção (Parque Durval de Barros),"
        "Ibirité,MG,32430275"
    )

    assert e.bairro == "Palmares - 4ª Seção (Parque Durval de Barros)"
    assert e.cidade == "Ibirité"


def test_sem_cep_so_com_cidade_uf():
    e = end.ler("Br 040 Km 688, Ceasa-Pav F Box 40, Kennedy, Contagem-MG")

    assert e.bairro == "Kennedy"
    assert e.cidade == "Contagem"


# ---------- o que NÃO pode virar bairro ----------


def test_endereco_de_uma_linha_so_nao_tem_bairro():
    """Inventar bairro é pior que admitir que não sabe."""
    assert end.ler("Acrópoluz Soluções em Iluminação").bairro is None


def test_numero_da_casa_nao_e_bairro():
    """"Rua X, 2350, Lagoa Santa - MG" não tem bairro; o que sobra na
    ponta é o número."""
    assert end.ler("Rua Padre Teixeira, 2350, Lagoa Santa - MG, 33400-000").bairro is None


def test_logradouro_repetido_nao_e_bairro():
    assert end.ler(
        "Rua N Senora do Perpetuo Socorro, Vespasiano - MG, 33200-000"
    ).bairro is None


def test_sigla_que_nao_e_uf_nao_vira_estado():
    """"Economart Escritório - BH": "BH" não é unidade federativa, e
    tratá-la como uma transformava o nome da empresa em cidade."""
    e = end.ler("Economart Escritório - BH")

    assert e.uf is None
    assert e.cidade is None


def test_texto_vazio_nao_quebra():
    assert end.ler("") == end.Endereco()
    assert end.ler(None) == end.Endereco()
    assert not end.ler("")


# ---------- a chave de agrupamento ----------


def test_mesmo_bairro_escrito_de_dois_jeitos_tem_a_mesma_chave():
    """"ESTORIL" e "Estoril" convivem no cadastro. Se virarem duas
    regiões, a equipe sai duas vezes para o mesmo lugar."""
    assert end.chave_regiao("ESTORIL", "BELO HORIZONTE") == \
           end.chave_regiao("Estoril", "Belo Horizonte")


def test_bairros_iguais_em_cidades_diferentes_nao_se_misturam():
    """"Centro" existe em BH, em Contagem e em Betim — a trinta
    quilômetros um do outro."""
    assert end.chave_regiao("Centro", "Belo Horizonte") != \
           end.chave_regiao("Centro", "Contagem")


def test_rotulo_mostra_bairro_e_cidade_em_caixa_uniforme():
    assert end.rotulo_regiao("PADRE EUSTÁQUIO", "belo horizonte") == \
           "Padre Eustáquio — Belo Horizonte"


def test_rotulo_preserva_particulas_minusculas():
    assert end.titulo("FAZENDA DO BENITO") == "Fazenda do Benito"


def test_rotulo_nao_estraga_o_que_nao_e_palavra():
    assert end.titulo("Palmares - 4ª Seção (Parque Durval de Barros)") == \
           "Palmares - 4ª Seção (Parque Durval de Barros)"


def test_rotulo_com_so_a_cidade():
    assert end.rotulo_regiao("", "CONTAGEM") == "Contagem"


def test_numero_colado_no_bairro_sem_hifen_e_descartado():
    """"592 Curralinho" é número da casa e bairro separados só por
    espaço."""
    assert end.ler("Rua das Flores, 592 Curralinho, Igarapé - MG").bairro == "Curralinho"


def test_numero_ordinal_no_comeco_do_bairro_e_preservado():
    """"4ª Seção" é nome de bairro de verdade — o "ª" é o que separa este
    caso do número da casa."""
    assert end.ler(
        "Rua Rio Grande,281,,4ª Seção (Parque Durval de Barros),Ibirité,MG,32430275"
    ).bairro == "4ª Seção (Parque Durval de Barros)"
