"""Leitura das planilhas que a Auvo e a PowerCentral exportam.

As duas são arquivos que vêm de fora, e o risco é o mesmo nas duas: ler a
coluna errada e seguir em frente em silêncio. Por isso coluna se acha
pelo **nome do cabeçalho**, nunca pela posição — basta alguém marcar uma
coluna a mais na tela de exportação para tudo deslocar.
"""

import io
import zipfile

import pytest

from app.domain import planilhas as pl

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _xlsx(linhas: list[list[str]]) -> bytes:
    """Monta um .xlsx mínimo, com strings inline."""
    corpo = []
    for n, linha in enumerate(linhas, start=1):
        celulas = "".join(
            f'<c r="{chr(65 + i)}{n}" t="inlineStr"><is><t>{v}</t></is></c>'
            for i, v in enumerate(linha)
            if v != ""
        )
        corpo.append(f'<row r="{n}">{celulas}</row>')
    sheet = (
        f'<?xml version="1.0"?><worksheet xmlns="{NS}"><sheetData>'
        + "".join(corpo)
        + "</sheetData></worksheet>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return buffer.getvalue()


def _html(linhas: list[list[str]]) -> bytes:
    corpo = "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in linha) + "</tr>" for linha in linhas
    )
    return f"<html><body><table>{corpo}</table></body></html>".encode("latin-1")


# ---------- qual arquivo é qual ----------


def test_detecta_pelo_conteudo_e_nao_pela_extensao():
    """O relatório da PowerCentral se chama .xls e por dentro é HTML.
    Fazer a pessoa acertar qual é qual seria passar para ela um problema
    que os dois primeiros bytes resolvem."""
    assert pl.detectar(_xlsx([["Nome"]])) == "auvo"
    assert pl.detectar(_html([["Nome"]])) == "power"


# ---------- Auvo ----------


def test_le_os_clientes_da_auvo():
    conteudo = _xlsx(
        [
            ["Código", "Nome", "Endereço"],
            ["", "Nome do cliente que será cadastrado...", "Endereço do cliente..."],
            ["17633114", "PADARIA DO ZE", "Rua X,10,,Centro,Belo Horizonte,MG,30100000"],
        ]
    )

    linhas = pl.ler_planilha_auvo(conteudo)

    assert len(linhas) == 1  # a linha de ajuda não é cliente
    assert linhas[0].id_auvo == 17633114
    assert linhas[0].nome == "PADARIA DO ZE"


def test_linha_de_ajuda_da_auvo_e_descartada_pelo_codigo():
    """Ela tem Nome e Endereço preenchidos com texto de instrução — o que
    a separa de um cliente é não ter Código."""
    conteudo = _xlsx(
        [["Código", "Nome", "Endereço"], ["", "Instrução qualquer", "Outra instrução"]]
    )

    assert pl.ler_planilha_auvo(conteudo) == []


def test_coluna_da_auvo_em_outra_posicao_continua_sendo_achada():
    conteudo = _xlsx(
        [
            ["Nome", "Telefone", "Código", "Segmento", "Endereço"],
            ["PADARIA", "31999", "500", "varejo", "Rua X,10,,Centro,BH,MG,30100000"],
        ]
    )

    linhas = pl.ler_planilha_auvo(conteudo)

    assert linhas[0].id_auvo == 500
    assert linhas[0].endereco.startswith("Rua X")


def test_planilha_da_auvo_sem_as_colunas_certas_e_recusada_com_instrucao():
    conteudo = _xlsx([["Coluna A", "Coluna B"], ["1", "2"]])

    with pytest.raises(pl.PlanilhaInvalida, match="Nome"):
        pl.ler_planilha_auvo(conteudo)


def test_celula_vazia_no_meio_nao_desloca_as_colunas():
    """O xlsx omite a célula vazia em vez de gravá-la. Sem olhar a
    referência ("C2"), tudo que vem depois anda uma casa para trás."""
    conteudo = _xlsx(
        [
            ["Código", "Nome", "Telefone", "Endereço"],
            ["500", "PADARIA", "", "Rua X,10,,Centro,BH,MG,30100000"],
        ]
    )

    assert pl.ler_planilha_auvo(conteudo)[0].endereco.startswith("Rua X")


# ---------- PowerCentral ----------


def test_le_as_contas_da_power():
    conteudo = _html(
        [
            ["Dealer / Conta", "Nome", "Localidade", "Rua"],
            ["MIL-0095", "PADARIA DO ZE", "BELO HORIZONTE", "AV. X, 10"],
        ]
    )

    linhas = pl.ler_planilha_power(conteudo)

    assert linhas[0].conta == "0095"  # "MIL-0095" vira o número
    assert linhas[0].cidade == "BELO HORIZONTE"


def test_relatorio_da_power_sem_tabela_explica_o_que_fazer():
    with pytest.raises(pl.PlanilhaInvalida, match="HTML"):
        pl.ler_planilha_power(b"isto nao e um relatorio")


def test_relatorio_da_power_sem_as_colunas_certas_e_recusado():
    conteudo = _html([["Coluna A", "Coluna B"], ["1", "2"]])

    with pytest.raises(pl.PlanilhaInvalida, match="Dealer / Conta"):
        pl.ler_planilha_power(conteudo)


def test_cabecalho_com_acento_e_caixa_diferentes_e_o_mesmo():
    conteudo = _html(
        [["DEALER / CONTA", "NOME", "LOCALIDADE"], ["MIL-0001", "CLIENTE", "CONTAGEM"]]
    )

    assert pl.ler_planilha_power(conteudo)[0].cidade == "CONTAGEM"
