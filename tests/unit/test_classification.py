from datetime import datetime
from zoneinfo import ZoneInfo

from app.domain.classification import FALSO_POSITIVO, SEM_COMUNICACAO, classificar_contas

FUSO = ZoneInfo("America/Sao_Paulo")
AGORA = datetime(2026, 7, 18, 12, 0, 0, tzinfo=FUSO)


def _conta(**overrides):
    base = {
        "cue_ncuenta": " 1001 ",
        "cue_cnombre": "Cliente Teste",
        "sta_ncuentaenfallodetst": "1",
        "sta_tEnFalloDeTSTDesde": "7/17/2026 8:00:00 AM",
        "sta_ncuentaenfallo2dotst": "0",
        "sta_tEnFalloDeTST2Desde": "1/1/1900 12:00:00 AM",
        "sta_ncuentaenfallo3ertst": "0",
        "sta_tEnFalloDeTST3Desde": "1/1/1900 12:00:00 AM",
        "cue_cUltimaAlarmaRecibida": "TST",
        "cue_dFechaUltimaAlarmaRecibida": "7/18/2026 11:00:00 AM",
    }
    base.update(overrides)
    return base


def test_conta_com_tst_recebido_ha_1h_nao_aparece_como_sem_comunicacao():
    # Critério de aceite: TST há 1h -> falso positivo (comunicando).
    contas = classificar_contas([_conta()], agora=AGORA)
    assert contas[0].classification == FALSO_POSITIVO
    assert contas[0].account_number == "1001"


def test_conta_com_ptb_ha_1h_aparece_como_sem_comunicacao():
    # Critério de aceite: PTB não é comprovador, mesmo recente.
    contas = classificar_contas(
        [
            _conta(
                cue_cUltimaAlarmaRecibida="PTB",
                cue_dFechaUltimaAlarmaRecibida="7/18/2026 11:00:00 AM",
            )
        ],
        agora=AGORA,
    )
    assert contas[0].classification == SEM_COMUNICACAO


def test_conta_com_tst_fora_da_janela_e_sem_comunicacao():
    contas = classificar_contas(
        [_conta(cue_dFechaUltimaAlarmaRecibida="7/18/2026 08:00:00 AM")],  # 4h atrás
        agora=AGORA,
        janela_horas=3,
    )
    assert contas[0].classification == SEM_COMUNICACAO


def test_conta_sem_ultimo_evento_e_sem_comunicacao():
    contas = classificar_contas(
        [_conta(cue_cUltimaAlarmaRecibida=None, cue_dFechaUltimaAlarmaRecibida=None)],
        agora=AGORA,
    )
    assert contas[0].classification == SEM_COMUNICACAO


def test_codigos_comprovadores_sao_configuraveis():
    contas = classificar_contas(
        [
            _conta(
                cue_cUltimaAlarmaRecibida="PAN",
                cue_dFechaUltimaAlarmaRecibida="7/18/2026 11:00:00 AM",
            )
        ],
        agora=AGORA,
        codigos_comprovadores=("TST", "CLO", "OPN", "PAN"),
    )
    assert contas[0].classification == FALSO_POSITIVO


def test_codigo_comprovador_e_case_insensitive():
    contas = classificar_contas(
        [_conta(cue_cUltimaAlarmaRecibida="tst")],
        agora=AGORA,
    )
    assert contas[0].classification == FALSO_POSITIVO


def test_falha_desde_usa_o_primeiro_teste_marcado():
    contas = classificar_contas([_conta()], agora=AGORA)
    assert contas[0].tst_failure_since == datetime(2026, 7, 17, 8, 0, 0, tzinfo=FUSO)


def test_falha_desde_usa_segundo_teste_quando_primeiro_nao_marcado():
    contas = classificar_contas(
        [
            _conta(
                sta_ncuentaenfallodetst="0",
                sta_tEnFalloDeTSTDesde="1/1/1900 12:00:00 AM",
                sta_ncuentaenfallo2dotst="1",
                sta_tEnFalloDeTST2Desde="7/16/2026 9:00:00 AM",
            )
        ],
        agora=AGORA,
    )
    assert contas[0].tst_failure_since == datetime(2026, 7, 16, 9, 0, 0, tzinfo=FUSO)


def test_numero_da_conta_e_normalizado_com_trim():
    contas = classificar_contas([_conta(cue_ncuenta="  2002  ")], agora=AGORA)
    assert contas[0].account_number == "2002"
