from app.domain.tecnico import (
    exportacao_recusada,
    montar_workbook_colorido,
    nome_arquivo_loja,
    nome_tecnico_da_tarefa,
    sanitizar_nome_arquivo,
    tecnico_corresponde,
)


# ---------- nome_tecnico_da_tarefa / tecnico_corresponde ----------


def test_nome_tecnico_usa_primeiro_campo_nao_vazio():
    assert nome_tecnico_da_tarefa({"userToName": "Alfredo Silva"}) == "Alfredo Silva"
    assert nome_tecnico_da_tarefa({"userToName": "", "idUserToName": "Henrique"}) == "Henrique"
    assert nome_tecnico_da_tarefa({"idUserTo": 159336}) == "159336"
    assert nome_tecnico_da_tarefa({}) == ""


def test_tecnico_corresponde_substring_sem_acento_case_insensitive():
    tarefa = {"userToName": "ALFRÉDO SILVA"}
    assert tecnico_corresponde(tarefa, "alfredo") is True
    assert tecnico_corresponde(tarefa, "Alfredo") is True
    assert tecnico_corresponde(tarefa, "SILVA") is True
    assert tecnico_corresponde(tarefa, "henrique") is False


def test_tecnico_vazio_significa_todos():
    assert tecnico_corresponde({"userToName": "Qualquer"}, "") is True
    assert tecnico_corresponde({}, "") is True


# ---------- nomes de arquivo ----------


def test_sanitizar_remove_caracteres_proibidos_e_trunca():
    assert sanitizar_nome_arquivo("SUPER NOSSO/CASTELO: LOJA #1") == "SUPER NOSSO_CASTELO_ LOJA _1"
    longo = "X" * 60
    assert len(sanitizar_nome_arquivo(longo)) == 40


def test_nome_arquivo_loja_com_zero_padding():
    assert nome_arquivo_loja("95", "CLINICA KENNEDY") == "0095_CLINICA KENNEDY.xls"
    assert nome_arquivo_loja("1234", "TESTE", extensao="xlsx") == "1234_TESTE.xlsx"


# ---------- exportacao_recusada ----------


def test_exportacao_recusada_detecta_erro_de_permissao():
    assert exportacao_recusada("<html>no se encontró la página</html>".encode()) is True
    assert exportacao_recusada("<html>Regularizar la situación</html>".encode()) is True
    assert exportacao_recusada("<html><table><tr><td>OK</td></tr></table></html>".encode()) is False


# ---------- montar_workbook_colorido ----------


HTML_EXEMPLO = """
<table>
<tr><th>Data e hora do evento</th><th>Evento</th><th>Zona</th></tr>
<tr>
  <td style="background-color:#00FFFF;color:#000000">31/07 08:22:01</td>
  <td style="background-color:#00FFFF">TST - Teste Periódico</td>
  <td></td>
</tr>
<tr>
  <td style="background-color:#FF6B00">31/07 07:05:55</td>
  <td style="background-color:#FF6B00">ARP - Acesso remoto</td>
  <td>&nbsp;</td>
</tr>
</table>
"""


def test_montar_workbook_preserva_cores_e_cabecalho():
    wb = montar_workbook_colorido(HTML_EXEMPLO)
    planilha = wb.active

    cabecalho = [c.value for c in planilha[1]]
    assert cabecalho == ["Data e hora do evento", "Evento", "Zona"]
    assert planilha["A1"].fill.fgColor.rgb == "0021A366"
    assert planilha["A1"].font.bold is True
    assert planilha.freeze_panes == "A2"

    linha2 = [c.value for c in planilha[2]]
    assert linha2[0] == "31/07 08:22:01"
    assert planilha["A2"].fill.fgColor.rgb == "FF00FFFF"

    linha3 = [c.value for c in planilha[3]]
    assert linha3[1] == "ARP - Acesso remoto"
    assert planilha["B3"].fill.fgColor.rgb == "FFFF6B00"


def test_montar_workbook_ignora_linhas_vazias():
    html = "<table><tr><td></td><td></td></tr><tr><td>Real</td></tr></table>"
    wb = montar_workbook_colorido(html)
    valores = [c.value for row in wb.active.iter_rows() for c in row if c.value]
    assert valores == ["Real"]
