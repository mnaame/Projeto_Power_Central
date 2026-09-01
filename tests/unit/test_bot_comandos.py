from app.domain.bot_comandos import (
    RESOLUCAO_AMBIGUA,
    RESOLUCAO_NAO_ENCONTRADA,
    RESOLUCAO_OK,
    formatar_ajuda,
    formatar_ambiguidade,
    formatar_resumo_relatorio,
    interpretar,
    resolver_conta,
    separar_conta_e_dias,
)

MAPA = {
    "95": ("9516", "AUTO MECANICA CENTRO"),
    "141": ("9520", "VILLEFORT FONTE GRANDE"),
    "10": ("9530", "VILLEFORT HM"),
    "11": ("9531", "VILLEFORT HM DEPOSITO"),
    "18": ("9540", "CONDOMINIO EDIFÍCIO VAN GOGH"),
}


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
