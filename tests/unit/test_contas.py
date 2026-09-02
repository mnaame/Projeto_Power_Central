from app.domain.contas import (
    Conta,
    contas_da_resposta,
    familia,
    ordenar,
    particoes_de,
)

# Formato REAL do CuentaByDealer sem o recorte cue_nparticion=0, conferido
# em produção com scripts/debug_particoes.py:
#   - cada partição é uma conta própria (cue_ncuenta e cue_iid próprios);
#   - cue_nparticion NÃO é o número da partição — é o cue_iid da MÃE;
#   - o vínculo legível vem em madre_ncuenta / madre_cnombre.
# Os campos vêm preenchidos com espaços à direita.
LINHAS = [
    {
        "cue_ncuenta": "0004    ", "cue_nparticion": "0", "cue_iid": "9385",
        "cue_cnombre": "VILLEFORT TROPICAL", "madre_ncuenta": "", "madre_cnombre": "",
    },
    {
        "cue_ncuenta": "0005    ", "cue_nparticion": "9385", "cue_iid": "9386",
        "cue_cnombre": "VILLEFORT ATACADISTA TROPICAL - TESOURARIA",
        "madre_ncuenta": "0004    ", "madre_cnombre": "VILLEFORT TROPICAL",
    },
    {
        "cue_ncuenta": "0095    ", "cue_nparticion": "0", "cue_iid": "9516",
        "cue_cnombre": "AUTO MECANICA CENTRO", "madre_ncuenta": "", "madre_cnombre": "",
    },
]


def test_le_numero_id_e_nome():
    contas = contas_da_resposta(LINHAS)
    assert contas[0] == Conta(numero="4", cue_iid="9385", nome="VILLEFORT TROPICAL")


def test_normaliza_numero_e_tira_espacos():
    assert contas_da_resposta(LINHAS)[2].numero == "95"


def test_particao_tem_numero_de_conta_proprio():
    """O detalhe que mudou o desenho: a tesouraria é a conta 5, não uma
    'partição 1' da conta 4."""
    particao = contas_da_resposta(LINHAS)[1]
    assert particao.numero == "5"
    assert particao.cue_iid == "9386"
    assert particao.identificacao == "5"


def test_vinculo_com_a_conta_mae():
    particao = contas_da_resposta(LINHAS)[1]
    assert particao.e_particao is True
    assert particao.conta_mae == "4"


def test_conta_principal_nao_e_particao():
    principal = contas_da_resposta(LINHAS)[0]
    assert principal.e_particao is False
    assert principal.conta_mae == ""


def test_cue_nparticion_zero_significa_conta_principal():
    """cue_nparticion guarda o cue_iid da mãe — 0 é 'não sou de ninguém'."""
    contas = contas_da_resposta(
        [{"cue_ncuenta": "0007", "cue_nparticion": "0", "cue_iid": "1", "madre_ncuenta": "0004"}]
    )
    assert contas[0].e_particao is False


def test_mae_apontando_para_si_mesma_e_ignorada():
    contas = contas_da_resposta(
        [{"cue_ncuenta": "0007", "cue_nparticion": "99", "cue_iid": "1", "madre_ncuenta": "0007"}]
    )
    assert contas[0].e_particao is False


def test_campos_ausentes_nao_quebram():
    contas = contas_da_resposta([{"cue_ncuenta": "0007", "cue_iid": "1"}])
    assert contas[0] == Conta(numero="7", cue_iid="1", nome="")


def test_linha_sem_id_e_descartada():
    assert contas_da_resposta([{"cue_ncuenta": "0043"}]) == []


def test_particoes_de_uma_conta():
    contas = contas_da_resposta(LINHAS)
    assert [c.numero for c in particoes_de(contas, "4")] == ["5"]
    assert particoes_de(contas, "95") == []


def test_familia_traz_a_mae_na_frente():
    contas = contas_da_resposta(LINHAS)
    mae = contas[0]
    assert [c.numero for c in familia(contas, mae)] == ["4", "5"]


def test_familia_de_conta_sem_particao_e_so_ela():
    contas = contas_da_resposta(LINHAS)
    assert familia(contas, contas[2]) == [contas[2]]


def test_ordena_por_numero_como_a_operacao_enxerga():
    contas = contas_da_resposta(list(reversed(LINHAS)))
    assert [c.numero for c in ordenar(contas)] == ["4", "5", "95"]
