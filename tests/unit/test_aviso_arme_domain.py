"""Ler a lista do Super Nosso e casar filial → conta, mais o diff semanal.

O risco deste módulo não é falhar em casar — é casar ERRADO: a filial
trocada é uma loja sem o aviso de arme, e o sistema não tem como
perceber. Por isso toda dúvida termina em "não casou" ou "ambígua", nunca
num palpite.
"""

from app.domain import aviso_arme as dom

MENSAGEM_REAL = """Bom dia! Segue a relação da semana para serviço noturno:
420 SN. FLEMING
688 SN. CASTELO
530 AP. VENDA NOVA
Qualquer coisa me avisa. Obrigado!"""


def _conta(iid, numero, nome):
    return dom.ContaAlvo(cue_iid=iid, numero=numero, nome=nome)


CADASTRO = [
    _conta("9001", "0002", "SUPER NOSSO FLEMING FILIAL 420 - LOJA"),
    _conta("9002", "0010", "SUPER NOSSO (CASTELO FILIAL 688)"),
    _conta("9003", "0011", "APOIO (VENDA NOVA FILIAL 530)"),
    _conta("9004", "0012", "SUPER NOSSO BURITIS FILIAL 999"),
]


# ---------- ler a mensagem ----------


def test_extrai_as_filiais_da_mensagem_escrita_por_gente():
    assert dom.extrair_filiais(MENSAGEM_REAL) == ["420", "688", "530"]


def test_preserva_a_ordem_da_mensagem():
    """Conferir duas listas na mesma ordem é o que torna a revisão
    possível."""
    assert dom.extrair_filiais("688\n420\n530") == ["688", "420", "530"]


def test_numero_repetido_entra_uma_vez_so():
    assert dom.extrair_filiais("420 SN FLEMING\n420 de novo") == ["420"]


def test_numero_grande_demais_nao_e_filial():
    """CNPJ, telefone e CEP vêm colados na mensagem o tempo todo."""
    assert dom.extrair_filiais("CNPJ 12345678000190, fone 999887766") == []


def test_zeros_a_esquerda_sao_a_mesma_filial():
    assert dom.extrair_filiais("0420") == ["420"]


def test_mensagem_sem_numero_nenhum():
    assert dom.extrair_filiais("Bom dia, segue a lista anexa") == []


# ---------- casar com o cadastro ----------


def test_casa_as_tres_filiais_da_lista_real():
    casados = dom.casar_filiais(dom.extrair_filiais(MENSAGEM_REAL), CADASTRO)

    assert [c.conta.numero for c in casados] == ["0002", "0010", "0011"]


def test_nome_abreviado_na_mensagem_nao_atrapalha():
    """"SN. FLEMING" não parece nada com "SUPER NOSSO FLEMING FILIAL 420".
    Quem casa é o número, e só ele."""
    casado = dom.casar_filiais(["420"], CADASTRO)[0]

    assert casado.conta.nome.startswith("SUPER NOSSO FLEMING")


def test_filial_que_nao_existe_fica_visivel_em_vez_de_sumir():
    casado = dom.casar_filiais(["777"], CADASTRO)[0]

    assert not casado.encontrada
    assert not casado.ambigua
    assert casado.filial == "777"


def test_filial_com_duas_contas_nao_escolhe_nenhuma():
    """Escolher "a primeira" colocaria em teste uma loja que talvez vá
    armar hoje à noite."""
    duplicado = CADASTRO + [_conta("9005", "0099", "SUPER NOSSO OUTRO FILIAL 420")]

    casado = dom.casar_filiais(["420"], duplicado)[0]

    assert casado.conta is None
    assert casado.ambigua
    assert len(casado.candidatas) == 2


def test_numero_solto_no_nome_so_vale_se_nao_houver_filial_explicita():
    """"FILIAL 688" ganha de um "688" perdido no meio de outro nome."""
    cadastro = [
        _conta("9010", "0020", "SUPER NOSSO CASTELO FILIAL 688"),
        _conta("9011", "0021", "SUPER NOSSO LOJA 688 BARREIRO FILIAL 700"),
    ]

    casado = dom.casar_filiais(["688"], cadastro)[0]

    assert casado.conta.numero == "0020"


def test_acento_e_caixa_no_nome_nao_atrapalham():
    cadastro = [_conta("9020", "0030", "Apoio (Venda Nova Filial 530)")]

    assert dom.casar_filiais(["530"], cadastro)[0].conta.numero == "0030"


# ---------- o diff da semana ----------


def _alvo(iid, numero):
    return dom.ContaAlvo(cue_iid=iid, numero=numero, nome=f"SN {numero} FILIAL {numero}")


def test_conta_nova_na_lista_entra_para_desligar():
    dif = dom.diferenca_da_semana([_alvo("1", "0001")], [])

    assert [c.cue_iid for c in dif.desligar] == ["1"]


def test_conta_que_saiu_da_lista_entra_para_religar():
    """O passo que o mecanismo anterior dispensava: lá a janela expirava
    sozinha, aqui alguém precisa religar."""
    dif = dom.diferenca_da_semana([_alvo("1", "0001")], ["1", "2"])

    assert dif.religar == ("2",)


def test_conta_que_continua_na_lista_nao_e_tocada():
    """Desligar de novo regravaria o ledger com `nnyc_original = 1`, ou
    seja, perderia para sempre o valor que a conta tinha antes. É o erro
    mais caro possível aqui."""
    dif = dom.diferenca_da_semana([_alvo("1", "0001")], ["1"])

    assert dif.desligar == ()
    assert dif.religar == ()
    assert [c.cue_iid for c in dif.ja_desligadas] == ["1"]


def test_semana_sem_mudanca_nao_gera_nada():
    dif = dom.diferenca_da_semana([], [])

    assert dif.desligar == () and dif.religar == ()


def test_lista_vazia_religa_tudo_o_que_estava_desligado():
    """É o que acontece na semana em que o Super Nosso não manda
    ninguém: tudo volta ao normal."""
    dif = dom.diferenca_da_semana([], ["1", "2"])

    assert dif.religar == ("1", "2")
