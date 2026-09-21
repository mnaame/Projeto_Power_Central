from app.domain import horarios as dom


def _linha(**extra):
    base = {"hor_choraapertura": "06:00", "hor_choracierre": "18:00"}
    base.update(extra)
    return base


def test_sem_linhas_e_conta_sem_horario():
    assert dom.tem_horario([]) is False


def test_com_linhas_e_conta_com_horario():
    assert dom.tem_horario([_linha()]) is True


def test_resumo_vazio_quando_nao_ha_horario():
    assert dom.resumo_horario([]) == ""


def test_resumo_traz_contagem_e_primeira_faixa():
    assert dom.resumo_horario([_linha(), _linha()]) == "2 faixa(s) 06:00–18:00"


def test_resumo_sem_faixa_legivel_mostra_so_a_contagem():
    """Linha existe mas sem hora preenchida: a conta TEM horário, então o
    resumo não pode ficar vazio (vazio é o sinal de 'sem horário')."""
    assert dom.resumo_horario([{"hor_choraapertura": "", "hor_choracierre": ""}]) == "1 faixa(s)"


# ----------------------------------------------------------------------
# Tipo da conta
# ----------------------------------------------------------------------


def test_tipo_vem_da_descricao_quando_a_linha_traz():
    linha = {"cue_ncuenta": "1", "tip_cDescripcion": "Comercial"}
    assert dom.tipo_da_conta(linha) == "Comercial"


def test_tipo_numerico_e_traduzido_pelo_catalogo():
    catalogo = dom.catalogo_de_tipos([{"Id": "4", "tip_cDescripcion": "Comercial"}])
    assert dom.tipo_da_conta({"_tip_nTipo": "4"}, catalogo) == "Comercial"


def test_tipo_numerico_com_decimal_tambem_casa():
    """O portal devolve o id ora como "4", ora como "4.0"."""
    catalogo = dom.catalogo_de_tipos([{"Id": "4", "tip_cDescripcion": "Comercial"}])
    assert dom.tipo_da_conta({"_tip_nTipo": "4.0"}, catalogo) == "Comercial"


def test_tipo_sem_campo_algum_fica_desconhecido():
    assert dom.tipo_da_conta({"cue_ncuenta": "1"}) == dom.TIPO_DESCONHECIDO


def test_numero_sem_traducao_fica_desconhecido():
    """Mostrar "4" na tela não ajuda ninguém a decidir se a conta precisa
    de horário — melhor assumir que não sabemos."""
    assert dom.tipo_da_conta({"_tip_nTipo": "9"}, {}) == dom.TIPO_DESCONHECIDO


def test_catalogo_ignora_linha_incompleta():
    catalogo = dom.catalogo_de_tipos([{"Id": "4"}, {"tip_cDescripcion": "Só nome"}])
    assert catalogo == {}


# ----------------------------------------------------------------------
# Filtros
# ----------------------------------------------------------------------


def _conta(conta="1", nome="LOJA", tipo="Comercial"):
    return dom.ContaAuditada(conta=conta, nome=nome, tipo=tipo)


def test_filtro_por_tipo_recorta_sem_diferenciar_caixa():
    itens = [_conta(tipo="Comercial"), _conta(conta="2", tipo="Residência")]
    assert [i.tipo for i in dom.filtrar_por_tipo(itens, ["comercial"])] == ["Comercial"]


def test_tipo_desconhecido_nunca_e_escondido_pelo_filtro():
    """Regra de segurança do módulo: se o portal não disse o que a conta é,
    esconder seria transformar limitação de integração em conta não
    auditada — exatamente o que o módulo existe para evitar."""
    itens = [_conta(tipo=dom.TIPO_DESCONHECIDO), _conta(conta="2", tipo="Residência")]
    resultado = dom.filtrar_por_tipo(itens, ["Comercial"])
    assert [i.conta for i in resultado] == ["1"]


def test_lista_de_tipos_vazia_nao_filtra_nada():
    itens = [_conta(tipo="Comercial"), _conta(conta="2", tipo="Residência")]
    assert len(dom.filtrar_por_tipo(itens, [])) == 2


def test_busca_livre_casa_nome_e_numero():
    itens = [_conta(conta="95", nome="VILLEFORT TROPICAL"), _conta(conta="7", nome="PADARIA")]
    assert [i.conta for i in dom.filtrar_por_nome(itens, "villefort")] == ["95"]
    assert [i.conta for i in dom.filtrar_por_nome(itens, "7")] == ["7"]
    assert len(dom.filtrar_por_nome(itens, "")) == 2
