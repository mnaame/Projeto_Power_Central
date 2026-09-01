from app.domain.contas import Conta, agrupar_por_numero
from app.domain.bot_comandos import (
    RESOLUCAO_AMBIGUA,
    RESOLUCAO_NAO_ENCONTRADA,
    RESOLUCAO_OK,
    RESOLUCAO_PARTICOES,
    filtrar_clientes,
    formatar_lista_clientes,
    formatar_particoes,
    separar_conta_e_particao,
    formatar_ajuda,
    formatar_ambiguidade,
    formatar_resumo_relatorio,
    interpretar,
    resolver_conta,
    separar_conta_e_dias,
)

CONTAS = [
    Conta("95", 0, "9516", "AUTO MECANICA CENTRO"),
    Conta("141", 0, "9520", "VILLEFORT FONTE GRANDE"),
    Conta("10", 0, "9530", "VILLEFORT HM"),
    Conta("11", 0, "9531", "VILLEFORT HM DEPOSITO"),
    Conta("18", 0, "9540", "CONDOMINIO EDIFÍCIO VAN GOGH"),
    # conta com partições (loja + tesouraria no mesmo local)
    Conta("43", 0, "9700", "PET PARA PETS"),
    Conta("43", 1, "9701", "PET PARA PETS - LOJA"),
    Conta("43", 2, "9702", "PET PARA PETS - TESOURARIA"),
]
MAPA = agrupar_por_numero(CONTAS)


# ---------- interpretar ----------


def test_comando_simples():
    comando = interpretar("/zona 95")
    assert comando.nome == "zona"
    assert comando.argumentos == ("95",)


def test_comando_com_nome_do_bot_em_grupo():
    # o Telegram acrescenta @bot quando o comando é dado num grupo
    assert interpretar("/zona@PowerCentralBot 95").nome == "zona"


def test_comando_ignora_caixa():
    assert interpretar("/ZONA 95").nome == "zona"


def test_texto_solto_nao_e_comando():
    assert interpretar("bom dia pessoal").nome == ""


def test_comando_desconhecido_e_ignorado():
    assert interpretar("/deletartudo").nome == ""


def test_comando_vazio():
    assert interpretar("").nome == ""


# ---------- separar_conta_e_dias ----------


def test_conta_sozinha_nao_vira_dias():
    assert separar_conta_e_dias(["9516"]) == ("9516", None)


def test_conta_e_dias():
    assert separar_conta_e_dias(["95", "15"]) == ("95", 15)


def test_nome_com_espacos_e_dias():
    assert separar_conta_e_dias(["AUTO", "MECANICA", "15"]) == ("AUTO MECANICA", 15)


def test_nome_com_espacos_sem_dias():
    assert separar_conta_e_dias(["AUTO", "MECANICA"]) == ("AUTO MECANICA", None)


def test_sem_argumentos():
    assert separar_conta_e_dias([]) == ("", None)


# ---------- resolver_conta ----------


def test_resolve_por_numero():
    resolucao = resolver_conta("95", MAPA)
    assert resolucao.status == RESOLUCAO_OK
    assert resolucao.conta.cue_iid == "9516"


def test_resolve_numero_com_zeros_a_esquerda():
    assert resolver_conta("0095", MAPA).conta.cue_iid == "9516"


def test_numero_inexistente():
    assert resolver_conta("77777", MAPA).status == RESOLUCAO_NAO_ENCONTRADA


def test_resolve_por_nome_parcial():
    resolucao = resolver_conta("auto mecanica", MAPA)
    assert resolucao.status == RESOLUCAO_OK
    assert resolucao.conta.numero == "95"


def test_nome_ignora_acento():
    assert resolver_conta("edificio van gogh", MAPA).status == RESOLUCAO_OK


def test_nome_ambiguo_nao_chuta():
    """Mandar o zoneamento da loja errada vaza o mapa de sensores de um
    cliente para outro — o bot pede o número em vez de escolher."""
    resolucao = resolver_conta("villefort", MAPA)
    assert resolucao.status == RESOLUCAO_AMBIGUA
    assert resolucao.conta is None
    assert len(resolucao.candidatas) == 3


def test_nome_exato_resolve_mesmo_sendo_prefixo_de_outro():
    # "VILLEFORT HM" está contido em "VILLEFORT HM DEPOSITO"
    resolucao = resolver_conta("villefort hm", MAPA)
    assert resolucao.status == RESOLUCAO_OK
    assert resolucao.conta.numero == "10"


def test_nome_inexistente():
    assert resolver_conta("padaria do joao", MAPA).status == RESOLUCAO_NAO_ENCONTRADA


def test_termo_vazio():
    assert resolver_conta("", MAPA).status == RESOLUCAO_NAO_ENCONTRADA


# ---------- formatação ----------


def test_ambiguidade_lista_numero_e_nome():
    texto = formatar_ambiguidade(resolver_conta("villefort", MAPA).candidatas)
    assert "Repita com o número" in texto
    assert "141 — VILLEFORT FONTE GRANDE" in texto


def test_resumo_do_relatorio():
    texto = formatar_resumo_relatorio(
        numero_conta="95", nome_cliente="AUTO MECANICA", dias=7, total_eventos=42
    )
    assert "95 AUTO MECANICA" in texto
    assert "7 dia(s)" in texto
    assert "42 evento(s)" in texto


def test_ajuda_cita_os_comandos():
    texto = formatar_ajuda()
    assert "/relatorio" in texto
    assert "/zona" in texto


# ---------- partições ----------


def test_separa_conta_e_particao():
    assert separar_conta_e_particao("43/2") == ("43", 2)


def test_sem_barra_particao_fica_indefinida():
    """None é diferente de 0: 0 é escolha explícita pela conta principal."""
    assert separar_conta_e_particao("43") == ("43", None)


def test_barra_com_lixo_nao_vira_particao():
    assert separar_conta_e_particao("43/x") == ("43/x", None)


def test_conta_sem_particoes_resolve_direto():
    resolucao = resolver_conta("95", MAPA)
    assert resolucao.status == RESOLUCAO_OK
    assert resolucao.conta.cue_iid == "9516"


def test_conta_com_particoes_pergunta_qual(app=None):
    """A partição errada é o setor errado do mesmo local — não se chuta."""
    resolucao = resolver_conta("43", MAPA)
    assert resolucao.status == RESOLUCAO_PARTICOES
    assert resolucao.conta is None
    assert [c.particao for c in resolucao.candidatas] == [0, 1, 2]


def test_particao_escolhida_resolve():
    resolucao = resolver_conta("43/2", MAPA)
    assert resolucao.status == RESOLUCAO_OK
    assert resolucao.conta.cue_iid == "9702"
    assert resolucao.conta.identificacao == "43/2"


def test_particao_inexistente_lista_as_que_existem():
    resolucao = resolver_conta("43/9", MAPA)
    assert resolucao.status == RESOLUCAO_PARTICOES
    assert len(resolucao.candidatas) == 3


def test_nome_de_conta_com_particoes_tambem_pergunta():
    resolucao = resolver_conta("pet para pets", MAPA)
    assert resolucao.status == RESOLUCAO_PARTICOES


def test_lista_de_particoes_traz_o_comando_pronto():
    texto = formatar_particoes(resolver_conta("43", MAPA).candidatas, comando="zona")
    assert "/zona 43/1 — PET PARA PETS - LOJA" in texto
    assert "/zona 43/2 — PET PARA PETS - TESOURARIA" in texto


def test_relatorio_com_particao_e_dias():
    termo, dias = separar_conta_e_dias(["43/2", "15"])
    assert (termo, dias) == ("43/2", 15)
    assert resolver_conta(termo, MAPA).conta.cue_iid == "9702"


# ---------- /clientes ----------


def test_lista_clientes_mostra_particoes_e_ordena_por_numero():
    texto = formatar_lista_clientes(CONTAS)
    linhas = [linha for linha in texto.split("\n") if linha and not linha.startswith("Clientes")]
    assert linhas[0] == "10 — VILLEFORT HM"
    assert "43/1 — PET PARA PETS - LOJA" in linhas
    assert "43 — PET PARA PETS" in linhas


def test_lista_clientes_conta_o_total():
    assert "(8)" in formatar_lista_clientes(CONTAS)


def test_filtro_por_nome():
    assert len(filtrar_clientes(CONTAS, "villefort")) == 3


def test_filtro_por_numero():
    assert [c.numero for c in filtrar_clientes(CONTAS, "43")] == ["43", "43", "43"]


def test_filtro_sem_resultado_avisa():
    texto = formatar_lista_clientes(filtrar_clientes(CONTAS, "padaria"), filtro="padaria")
    assert "Nenhum cliente encontrado" in texto


def test_sem_filtro_devolve_tudo():
    assert len(filtrar_clientes(CONTAS, "")) == len(CONTAS)


def test_ajuda_cita_clientes_e_particao():
    texto = formatar_ajuda()
    assert "/clientes" in texto
    assert "95/2" in texto
