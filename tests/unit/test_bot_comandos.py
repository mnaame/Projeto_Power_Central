from app.domain.contas import Conta
from app.domain.bot_comandos import (
    RESOLUCAO_AMBIGUA,
    RESOLUCAO_NAO_ENCONTRADA,
    RESOLUCAO_OK,
    RESOLUCAO_PARTICOES,
    filtrar_clientes,
    formatar_ajuda,
    formatar_ambiguidade,
    formatar_lista_clientes,
    formatar_particoes,
    formatar_resumo_relatorio,
    interpretar,
    resolver_conta,
    separar_conta_e_dias,
)

# Espelha a base real: partição é conta própria, ligada à mãe por número.
CONTAS = [
    Conta("95", "9516", "AUTO MECANICA CENTRO"),
    Conta("141", "9520", "VILLEFORT FONTE GRANDE"),
    Conta("10", "9530", "VILLEFORT HM"),
    Conta("11", "9531", "VILLEFORT HM DEPOSITO"),
    Conta("18", "9540", "CONDOMINIO EDIFÍCIO VAN GOGH"),
    # local com tesouraria separada (caso real VILLEFORT TROPICAL 4 -> 5)
    Conta("4", "9385", "VILLEFORT TROPICAL"),
    Conta("5", "9386", "VILLEFORT ATACADISTA TROPICAL - TESOURARIA", conta_mae="4"),
]
MAPA = CONTAS


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
    assert len(resolucao.candidatas) == 5


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


def test_conta_sem_particao_resolve_direto():
    resolucao = resolver_conta("95", MAPA)
    assert resolucao.status == RESOLUCAO_OK
    assert resolucao.conta.cue_iid == "9516"


def test_particao_resolve_direto_pelo_numero_dela():
    """Partição tem número próprio — não precisa de sintaxe especial."""
    resolucao = resolver_conta("5", MAPA)
    assert resolucao.status == RESOLUCAO_OK
    assert resolucao.conta.cue_iid == "9386"
    assert resolucao.conta.e_particao is True


def test_pedir_a_conta_mae_pergunta_de_qual_setor():
    """"O histórico da VILLEFORT TROPICAL" pode ser a loja ou a
    tesouraria — entregar o setor errado é entregar a informação errada."""
    resolucao = resolver_conta("4", MAPA)
    assert resolucao.status == RESOLUCAO_PARTICOES
    assert resolucao.conta is None
    assert [c.numero for c in resolucao.candidatas] == ["4", "5"]


def test_nome_da_conta_mae_tambem_pergunta():
    assert resolver_conta("villefort tropical", MAPA).status == RESOLUCAO_PARTICOES


def test_nome_da_particao_resolve_direto():
    resolucao = resolver_conta("tesouraria", MAPA)
    assert resolucao.status == RESOLUCAO_OK
    assert resolucao.conta.numero == "5"


def test_lista_de_particoes_traz_o_comando_pronto():
    texto = formatar_particoes(resolver_conta("4", MAPA).candidatas, comando="zona")
    assert "/zona 4 — VILLEFORT TROPICAL" in texto
    assert "/zona 5 — VILLEFORT ATACADISTA TROPICAL - TESOURARIA  (partição)" in texto


def test_relatorio_de_particao_com_dias():
    termo, dias = separar_conta_e_dias(["5", "15"])
    assert (termo, dias) == ("5", 15)
    assert resolver_conta(termo, MAPA).conta.cue_iid == "9386"


# ---------- /clientes ----------


def test_lista_clientes_ordena_por_numero():
    texto = formatar_lista_clientes(CONTAS)
    linhas = [linha for linha in texto.split("\n") if linha and not linha.startswith("Clientes")]
    assert linhas[0] == "4 — VILLEFORT TROPICAL"


def test_lista_clientes_mostra_de_quem_a_particao_e():
    """Sem isso o técnico não sabe de qual local aquele número faz parte."""
    texto = formatar_lista_clientes(CONTAS)
    linha = [linha for linha in texto.split("\n") if linha.startswith("5 —")][0]
    assert "[part. de 4]" in linha


def test_lista_clientes_conta_o_total():
    assert "(7)" in formatar_lista_clientes(CONTAS)


def test_filtro_por_nome():
    assert len(filtrar_clientes(CONTAS, "villefort")) == 5


def test_filtro_por_numero():
    assert [c.numero for c in filtrar_clientes(CONTAS, "141")] == ["141"]


def test_filtro_sem_resultado_avisa():
    texto = formatar_lista_clientes(filtrar_clientes(CONTAS, "padaria"), filtro="padaria")
    assert "Nenhum cliente encontrado" in texto


def test_sem_filtro_devolve_tudo():
    assert len(filtrar_clientes(CONTAS, "")) == len(CONTAS)


def test_ajuda_cita_clientes_e_particao():
    texto = formatar_ajuda()
    assert "/clientes" in texto
    assert "partição" in texto
