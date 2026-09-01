from app.domain.tecnico import (
    exportacao_recusada,
    horario_da_tarefa,
    id_cliente_da_tarefa,
    mapa_contas,
    montar_workbook_colorido,
    nome_arquivo_loja,
    nome_cliente_da_tarefa,
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


# ---------- id/nome do cliente e horário da tarefa ----------


def test_id_cliente_da_tarefa_primeiro_campo_valido():
    assert id_cliente_da_tarefa({"customerId": 13804973}) == 13804973
    assert id_cliente_da_tarefa({"idCustomer": "13804973"}) == 13804973
    assert id_cliente_da_tarefa({"customerId": "não é número"}) is None
    assert id_cliente_da_tarefa({}) is None


def test_nome_cliente_da_tarefa_cai_para_id_quando_sem_nome():
    assert nome_cliente_da_tarefa({"customerDescription": "CLINICA KENNEDY"}) == "CLINICA KENNEDY"
    assert nome_cliente_da_tarefa({"customerId": 123}) == "123"
    assert nome_cliente_da_tarefa({}) == ""


def test_horario_da_tarefa_vazio_quando_nenhum_campo_conhecido():
    assert horario_da_tarefa({"taskDate": "2026-07-31T08:00:00"}) == "2026-07-31T08:00:00"
    assert horario_da_tarefa({}) == ""


# ---------- mapa_contas ----------


def test_mapa_contas_normaliza_numero_e_ignora_sem_id_interno():
    contas = [
        {"cue_ncuenta": "0095", "cue_iid": "9385", "cue_cnombre": "CLINICA KENNEDY"},
        {"cue_ncuenta": "0004", "cue_iid": 4021, "cue_cnombre": "VILLEFORT TROPICAL"},
        {"cue_ncuenta": "0099", "cue_cnombre": "SEM ID INTERNO"},
    ]
    mapa = mapa_contas(contas)
    assert mapa == {
        "95": ("9385", "CLINICA KENNEDY"),
        "4": ("4021", "VILLEFORT TROPICAL"),
    }


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


# ---------- contar_eventos_do_export ----------


def test_conta_eventos_ignorando_cabecalho_e_linhas_vazias():
    from app.domain.tecnico import contar_eventos_do_export

    assert contar_eventos_do_export(HTML_EXEMPLO) == 2


def test_conta_eventos_aceita_bytes():
    from app.domain.tecnico import contar_eventos_do_export

    assert contar_eventos_do_export(HTML_EXEMPLO.encode()) == 2


def test_conta_eventos_export_vazio():
    from app.domain.tecnico import contar_eventos_do_export

    html = "<table><tr><th>Data e hora do evento</th></tr></table>"
    assert contar_eventos_do_export(html) == 0
