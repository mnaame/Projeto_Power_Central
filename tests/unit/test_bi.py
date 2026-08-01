from datetime import datetime, timedelta, timezone

from app.domain.bi import (
    CLASSIFICACAO_ESTAVEL,
    CLASSIFICACAO_MELHOROU,
    CLASSIFICACAO_PIOROU,
    CLASSIFICACAO_SEM_BASE,
    Intervencao,
    classificar_janela,
    clientes_cronicos,
    data_conclusao,
    resumo_por_tecnico,
    tarefa_concluida,
    tem_atribuicao_compartilhada,
)
from app.domain.disparos import DisparoAvaliado

MARCO = datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc)


def _disparo(dias_do_marco: float, *, valido: bool = True) -> DisparoAvaliado:
    return DisparoAvaliado(
        quando=MARCO + timedelta(days=dias_do_marco),
        zona="ZONA 1",
        id_evento="1",
        atendido=True,
        valido=valido,
        motivo_exclusao=None if valido else "rotina",
    )


# ---------- tarefa_concluida ----------


def test_tarefa_concluida_por_finished():
    assert tarefa_concluida({"finished": True}) is True


def test_tarefa_concluida_por_task_status():
    assert tarefa_concluida({"finished": False, "taskStatus": 5}) is True


def test_tarefa_nao_concluida():
    assert tarefa_concluida({"finished": False, "taskStatus": 3}) is False
    assert tarefa_concluida({}) is False


# ---------- data_conclusao ----------


def test_data_conclusao_usa_primeiro_candidato_valido():
    data = data_conclusao({"checkOutDatetime": "2026-07-15T14:30:00"})
    assert data is not None
    assert (data.year, data.month, data.day, data.hour, data.minute) == (2026, 7, 15, 14, 30)


def test_data_conclusao_aceita_sufixo_z():
    data = data_conclusao({"finishedDate": "2026-07-15T14:30:00Z"})
    assert data is not None
    assert data.year == 2026 and data.hour == 14


def test_data_conclusao_cai_para_task_date_como_ultimo_recurso():
    data = data_conclusao({"taskDate": "2026-07-15T08:00:00"})
    assert data is not None
    assert data.day == 15


def test_data_conclusao_none_quando_nenhum_campo_bate():
    assert data_conclusao({}) is None
    assert data_conclusao({"checkOutDatetime": "não é data"}) is None


# ---------- classificar_janela ----------


def test_classificar_melhorou_quando_cai_acima_do_limiar():
    avaliados = [_disparo(-d) for d in (1, 2, 3, 4, 5)] + [_disparo(d) for d in (1,)]
    agora = MARCO + timedelta(days=15)
    resultado = classificar_janela(avaliados, marco=MARCO, agora=agora)
    assert resultado.antes_por_dia == 5 / 15
    assert resultado.depois_por_dia == 1 / 15
    assert resultado.classificacao == CLASSIFICACAO_MELHOROU
    assert resultado.parcial is False


def test_classificar_piorou_quando_sobe_acima_do_limiar():
    avaliados = [_disparo(-1)] + [_disparo(d) for d in (1, 2, 3, 4, 5)]
    agora = MARCO + timedelta(days=15)
    resultado = classificar_janela(avaliados, marco=MARCO, agora=agora)
    assert resultado.classificacao == CLASSIFICACAO_PIOROU


def test_classificar_estavel_quando_variacao_pequena():
    avaliados = [_disparo(-d) for d in range(1, 6)] + [_disparo(d) for d in range(1, 6)]
    agora = MARCO + timedelta(days=15)
    resultado = classificar_janela(avaliados, marco=MARCO, agora=agora)
    assert resultado.classificacao == CLASSIFICACAO_ESTAVEL
    assert resultado.variacao_pct == 0.0


def test_classificar_sem_base_quando_nao_havia_disparo_antes():
    avaliados = [_disparo(1), _disparo(2)]
    agora = MARCO + timedelta(days=15)
    resultado = classificar_janela(avaliados, marco=MARCO, agora=agora)
    assert resultado.classificacao == CLASSIFICACAO_SEM_BASE
    assert resultado.variacao_pct is None
    assert resultado.antes_por_dia == 0.0


def test_classificar_parcial_quando_janela_depois_ainda_nao_fechou():
    avaliados = [_disparo(-1), _disparo(1)]
    agora = MARCO + timedelta(days=5)  # só 5 dos 15 dias do "depois" já passaram
    resultado = classificar_janela(avaliados, marco=MARCO, agora=agora)
    assert resultado.parcial is True
    assert resultado.dias_depois == 5
    assert resultado.depois_por_dia == 1 / 5


def test_classificar_ignora_disparos_invalidos():
    avaliados = [_disparo(-1, valido=False), _disparo(-1, valido=True)]
    agora = MARCO + timedelta(days=15)
    resultado = classificar_janela(avaliados, marco=MARCO, agora=agora)
    assert resultado.antes_por_dia == 1 / 15


# ---------- tem_atribuicao_compartilhada ----------


def test_atribuicao_compartilhada_true_quando_outra_visita_no_depois():
    outra = MARCO + timedelta(days=5)
    assert tem_atribuicao_compartilhada([MARCO, outra], marco=MARCO) is True


def test_atribuicao_compartilhada_false_quando_unica_visita():
    assert tem_atribuicao_compartilhada([MARCO], marco=MARCO) is False


def test_atribuicao_compartilhada_false_quando_outra_visita_fora_da_janela():
    outra = MARCO + timedelta(days=30)
    assert tem_atribuicao_compartilhada([MARCO, outra], marco=MARCO, janela_dias=15) is False


# ---------- resumo_por_tecnico / clientes_cronicos ----------


def _intervencao(
    *,
    conta="95",
    tecnico="Alfredo",
    marco=MARCO,
    antes=1.0,
    depois=0.2,
    classificacao=CLASSIFICACAO_MELHOROU,
    dias_depois=15,
) -> Intervencao:
    return Intervencao(
        task_id_auvo="1",
        conta_power=conta,
        id_auvo_cliente=123,
        nome_loja=f"LOJA {conta}",
        tecnico_nome=tecnico,
        marco=marco,
        antes_por_dia=antes,
        depois_por_dia=depois,
        variacao_pct=((depois - antes) / antes * 100) if antes else None,
        classificacao=classificacao,
        parcial=False,
        atribuicao_compartilhada=False,
        dias_depois=dias_depois,
    )


def test_resumo_por_tecnico_agrega_e_sinaliza_amostra_pequena():
    intervencoes = [
        _intervencao(conta="95", classificacao=CLASSIFICACAO_MELHOROU),
        _intervencao(conta="4", classificacao=CLASSIFICACAO_PIOROU, antes=1.0, depois=2.0),
    ]
    resumo = resumo_por_tecnico(intervencoes, amostra_minima=5)
    assert len(resumo) == 1
    r = resumo[0]
    assert r.tecnico == "Alfredo"
    assert r.total_intervencoes == 2
    assert r.total_melhorou == 1
    assert r.total_piorou == 1
    assert r.amostra_pequena is True


def test_resumo_por_tecnico_disparos_evitados():
    intervencoes = [_intervencao(antes=2.0, depois=0.5, dias_depois=10)]
    resumo = resumo_por_tecnico(intervencoes, amostra_minima=1)
    assert resumo[0].disparos_evitados == 15.0  # (2.0 - 0.5) * 10
    assert resumo[0].amostra_pequena is False


def test_clientes_cronicos_exige_minimo_de_visitas_e_ainda_disparando():
    intervencoes = [
        _intervencao(conta="95", marco=MARCO, depois=0.5),
        _intervencao(conta="95", marco=MARCO + timedelta(days=20), depois=0.3),
        _intervencao(conta="95", marco=MARCO + timedelta(days=40), depois=0.4),
    ]
    cronicos = clientes_cronicos(intervencoes, visitas_para_cronico=3)
    assert len(cronicos) == 1
    assert cronicos[0].conta_power == "95"
    assert cronicos[0].total_visitas == 3
    assert cronicos[0].disparos_por_dia_atual == 0.4  # visita mais recente


def test_clientes_cronicos_exclui_quem_parou_de_disparar():
    intervencoes = [
        _intervencao(conta="95", marco=MARCO, depois=0.5),
        _intervencao(conta="95", marco=MARCO + timedelta(days=20), depois=0.3),
        _intervencao(conta="95", marco=MARCO + timedelta(days=40), depois=0.0),
    ]
    assert clientes_cronicos(intervencoes, visitas_para_cronico=3) == []


def test_clientes_cronicos_exclui_abaixo_do_minimo_de_visitas():
    intervencoes = [_intervencao(conta="95", depois=0.5)]
    assert clientes_cronicos(intervencoes, visitas_para_cronico=3) == []
