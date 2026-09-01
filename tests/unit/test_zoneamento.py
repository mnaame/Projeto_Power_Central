from app.domain.zoneamento import Zona, formatar_zoneamento, zonas_da_resposta

# Formato real da resposta de /Rest/Zona/ (HAR de 01/09): o código vem
# preenchido com espaços à direita.
LINHAS = [
    {"zon_ccodigo": "1   ", "zon_cdescripcion": "MAG PORTÕES GARAGEM", "zon_cAlarmaAGenerar": "NYR"},
    {"zon_ccodigo": "2   ", "zon_cdescripcion": "MAG PORTA SALA", "zon_cAlarmaAGenerar": "NYR"},
    {"zon_ccodigo": "SP1 ", "zon_cdescripcion": "SENTINELLA: SOS - PÂNICO", "zon_cAlarmaAGenerar": ""},
]


def test_le_codigo_descricao_e_alarme():
    zonas = zonas_da_resposta(LINHAS)
    assert len(zonas) == 3
    assert zonas[0] == Zona(codigo="1", descricao="MAG PORTÕES GARAGEM", alarme="NYR")


def test_codigo_vem_com_espacos_e_e_limpo():
    assert zonas_da_resposta(LINHAS)[2].codigo == "SP1"


def test_preserva_a_ordem_do_portal():
    """A consulta já pede orderCodigo ASC — reordenar aqui mudaria a ordem
    que o técnico vê na tela do portal."""
    assert [z.codigo for z in zonas_da_resposta(LINHAS)] == ["1", "2", "SP1"]


def test_linha_sem_codigo_e_descartada():
    linhas = LINHAS + [{"zon_ccodigo": "   ", "zon_cdescripcion": "LIXO"}]
    assert len(zonas_da_resposta(linhas)) == 3


def test_campos_ausentes_nao_quebram():
    zonas = zonas_da_resposta([{"zon_ccodigo": "7"}])
    assert zonas[0] == Zona(codigo="7", descricao="", alarme="")


def test_formatacao_tem_cabecalho_total_e_linhas():
    texto = formatar_zoneamento(
        zonas_da_resposta(LINHAS), numero_conta="9516", nome_cliente="AUTO MECANICA"
    )
    linhas = texto.split("\n")
    assert linhas[0] == "Zoneamento — 9516 AUTO MECANICA"
    assert linhas[1] == "Total: 3 zona(s)"
    assert "MAG PORTA SALA" in texto
    assert "(NYR)" in texto


def test_zona_sem_alarme_nao_mostra_parenteses_vazio():
    texto = formatar_zoneamento(
        zonas_da_resposta(LINHAS), numero_conta="9516", nome_cliente="X"
    )
    linha_sp1 = [linha for linha in texto.split("\n") if linha.startswith("SP1")][0]
    assert linha_sp1.endswith("SENTINELLA: SOS - PÂNICO")


def test_colunas_alinhadas():
    texto = formatar_zoneamento(
        zonas_da_resposta(LINHAS), numero_conta="9516", nome_cliente="X"
    )
    com_alarme = [linha for linha in texto.split("\n") if "(NYR)" in linha]
    assert len({linha.index("(NYR)") for linha in com_alarme}) == 1


def test_conta_sem_zona_avisa():
    texto = formatar_zoneamento([], numero_conta="9516", nome_cliente="X")
    assert "Nenhuma zona cadastrada" in texto
