from app.domain.contas import (
    Conta,
    agrupar_por_numero,
    contas_da_resposta,
    escolher_particao,
    tem_particoes,
)

# Formato de CuentaByDealer sem o recorte cue_nparticion=0: cada partição
# é uma linha própria, com o mesmo cue_ncuenta e seu próprio cue_iid.
LINHAS = [
    {"cue_ncuenta": "0043", "cue_nparticion": 0, "cue_iid": "9700", "cue_cnombre": "PET PARA PETS"},
    {"cue_ncuenta": "0043", "cue_nparticion": 1, "cue_iid": "9701", "cue_cnombre": "PET - LOJA"},
    {"cue_ncuenta": "0095", "cue_nparticion": 0, "cue_iid": "9516", "cue_cnombre": "AUTO MECANICA"},
]


def test_le_numero_particao_id_e_nome():
    contas = contas_da_resposta(LINHAS)
    assert contas[0] == Conta(numero="43", particao=0, cue_iid="9700", nome="PET PARA PETS")


def test_normaliza_o_numero_sem_zeros_a_esquerda():
    assert contas_da_resposta(LINHAS)[2].numero == "95"


def test_particao_ausente_vira_conta_principal():
    contas = contas_da_resposta([{"cue_ncuenta": "0095", "cue_iid": "9516"}])
    assert contas[0].particao == 0


def test_particao_como_texto_e_aceita():
    contas = contas_da_resposta([{"cue_ncuenta": "43", "cue_nparticion": "2", "cue_iid": "9702"}])
    assert contas[0].particao == 2


def test_particao_invalida_nao_quebra():
    """Defensivo: pior caso é uma opção a mais na lista, nunca um erro."""
    contas = contas_da_resposta([{"cue_ncuenta": "43", "cue_nparticion": "x", "cue_iid": "9702"}])
    assert contas[0].particao == 0


def test_linha_sem_id_e_descartada():
    assert contas_da_resposta([{"cue_ncuenta": "0043"}]) == []


def test_agrupa_por_numero_e_ordena_por_particao():
    agrupado = agrupar_por_numero(
        contas_da_resposta(list(reversed(LINHAS)))
    )
    assert [c.particao for c in agrupado["43"]] == [0, 1]
    assert len(agrupado["95"]) == 1


def test_tem_particoes():
    agrupado = agrupar_por_numero(contas_da_resposta(LINHAS))
    assert tem_particoes(agrupado["43"]) is True
    assert tem_particoes(agrupado["95"]) is False


def test_escolher_particao():
    agrupado = agrupar_por_numero(contas_da_resposta(LINHAS))
    assert escolher_particao(agrupado["43"], 1).cue_iid == "9701"
    assert escolher_particao(agrupado["43"], 9) is None


def test_identificacao_e_rotulo():
    principal, particao = contas_da_resposta(LINHAS)[:2]
    assert principal.identificacao == "43"
    assert particao.identificacao == "43/1"
    assert particao.rotulo == "43/1 — PET - LOJA"


def test_sufixo_de_arquivo_separa_as_particoes():
    """Sem isso, duas partições da mesma conta gerariam arquivos de nome
    igual no mesmo chat."""
    principal, particao = contas_da_resposta(LINHAS)[:2]
    assert principal.sufixo_arquivo == ""
    assert particao.sufixo_arquivo == " P1"
