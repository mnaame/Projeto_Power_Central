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
# Filtro
# ----------------------------------------------------------------------


def _conta(conta="1", nome="LOJA"):
    return dom.ContaAuditada(conta=conta, nome=nome)


def test_busca_livre_casa_nome_e_numero():
    itens = [_conta(conta="95", nome="VILLEFORT TROPICAL"), _conta(conta="7", nome="PADARIA")]
    assert [i.conta for i in dom.filtrar_por_nome(itens, "villefort")] == ["95"]
    assert [i.conta for i in dom.filtrar_por_nome(itens, "7")] == ["7"]


def test_busca_vazia_nao_filtra_nada():
    """Em branco = varrer a base inteira, residência inclusive."""
    itens = [_conta(conta="95"), _conta(conta="7")]
    assert len(dom.filtrar_por_nome(itens, "")) == 2
