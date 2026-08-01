from datetime import datetime, timedelta

import pytest

from app.domain.dates import FUSO_HORARIO
from app.extensions import db
from app.models.auvo import AuvoDepara
from app.models.bi import BiRun
from app.services import bi_service, settings_service

AGORA = datetime.now(FUSO_HORARIO)
MARCO_FECHADO = AGORA - timedelta(days=20)  # "depois" (15d) já fechou por completo


def _fmt(dt: datetime) -> str:
    return dt.strftime("%m/%d/%Y %I:%M:%S %p")


class FakeAuvoClient:
    def __init__(self, tarefas=None):
        self.tarefas = tarefas or []
        self.chamadas = []

    def listar_tarefas(self, data_inicio, data_fim):
        self.chamadas.append((data_inicio, data_fim))
        return self.tarefas


class FakeSoftGuardClient:
    def __init__(self, eventos=None):
        self.eventos = eventos or []
        self.chamadas = []

    def buscar_historico(self, *, codigos_alarme, desde, hasta, **kwargs):
        self.chamadas.append(
            {"codigos": tuple(codigos_alarme), "desde": desde, "hasta": hasta, **kwargs}
        )
        return self.eventos


def _tarefa(
    customer_id,
    marco: datetime | None,
    *,
    finished=True,
    task_status=5,
    tecnico="Alfredo Silva",
    task_type=145696,
    campo_data="checkOutDatetime",
):
    tarefa = {
        "customerId": customer_id,
        "finished": finished,
        "taskStatus": task_status,
        "userToName": tecnico,
        "taskType": task_type,
    }
    if marco is not None:
        tarefa[campo_data] = marco.strftime("%Y-%m-%dT%H:%M:%S")
    return tarefa


def _evento(conta_zero_padded: str, codigo: str, quando: datetime) -> dict:
    return {
        "cue_ncuenta": conta_zero_padded,
        "cue_cnombre": f"CLIENTE {conta_zero_padded}",
        "rec_calarma": codigo,
        "rec_tfechahora": _fmt(quando),
        "rec_iidcuenta": "9385",
        "rec_iid": f"{conta_zero_padded}-{codigo}-{quando.timestamp()}",
    }


def _depara(conta="95", id_auvo=13804973, status="OK", nome="CLIENTE 95"):
    linha = AuvoDepara(conta_power=conta, nome_power=nome, id_auvo=id_auvo, status=status)
    db.session.add(linha)
    db.session.commit()
    return linha


def _eventos_melhorou(conta="0095", marco=MARCO_FECHADO):
    return (
        [_evento(conta, "BUR", marco - timedelta(days=d)) for d in (1, 2, 3, 4, 5)]
        + [_evento(conta, "BUR", marco + timedelta(days=1))]
    )


# ---------- recalcular: fim a fim ----------


def test_recalcular_gera_intervencao_com_vinculo(app):
    _depara(conta="95", id_auvo=13804973)
    auvo = FakeAuvoClient(tarefas=[_tarefa(13804973, MARCO_FECHADO)])
    softguard = FakeSoftGuardClient(eventos=_eventos_melhorou())

    run = bi_service.recalcular(
        config=app.config,
        periodo_desde=AGORA - timedelta(days=90),
        periodo_hasta=AGORA,
        auvo_client=auvo,
        softguard_client=softguard,
    )

    assert run.status == "success"
    assert len(auvo.chamadas) == 1
    assert len(softguard.chamadas) == 1  # uma única chamada de histórico
    assert softguard.chamadas[0]["page_size"] == bi_service.PAGE_SIZE_HISTORICO
    assert run.resumo["total_intervencoes"] == 1
    assert run.resumo["melhorou"] == 1
    assert run.resumo["sem_vinculo"] == 0
    assert run.resumo["sem_data"] == 0

    intervencao = run.intervencoes[0]
    assert intervencao.conta_power == "95"
    assert intervencao.classificacao == "MELHOROU"
    assert intervencao.parcial is False


def test_recalcular_aceita_override_de_janela_e_limiar(app):
    """Sem override o cenário classifica MELHOROU (queda de 80%, >= 20%
    padrão); com janela menor (3 dias) o disparo do "depois" (dia +1) fica
    fora da janela — vira SEM_BASE por antes/dia zerar do outro lado? Não:
    aqui só confirma que o override É USADO (troca janela_dias do run) e
    reflete na intervenção persistida."""
    _depara(conta="95", id_auvo=13804973)
    auvo = FakeAuvoClient(tarefas=[_tarefa(13804973, MARCO_FECHADO)])
    softguard = FakeSoftGuardClient(eventos=_eventos_melhorou())

    run = bi_service.recalcular(
        config=app.config,
        periodo_desde=AGORA - timedelta(days=90),
        periodo_hasta=AGORA,
        janela_dias=3,
        limiar_melhora_pct=5,
        limiar_piora_pct=5,
        auvo_client=auvo,
        softguard_client=softguard,
    )

    assert run.janela_dias == 3
    assert run.limiar_melhora_pct == 5
    assert run.limiar_piora_pct == 5
    intervencao = run.intervencoes[0]
    # janela de 3 dias só enxerga 3 dos 5 disparos do "antes" (a -1,-2,-3)
    assert intervencao.antes_por_dia == 3 / 3
    assert intervencao.dias_depois == 3


def test_recalcular_conta_sem_vinculo_fica_fora_do_calculo(app):
    auvo = FakeAuvoClient(tarefas=[_tarefa(999999, MARCO_FECHADO)])
    softguard = FakeSoftGuardClient(eventos=[])

    run = bi_service.recalcular(
        config=app.config,
        periodo_desde=AGORA - timedelta(days=90),
        periodo_hasta=AGORA,
        auvo_client=auvo,
        softguard_client=softguard,
    )

    assert run.status == "success"
    assert run.resumo["total_intervencoes"] == 0
    assert run.resumo["sem_vinculo"] == 1
    assert len(softguard.chamadas) == 0  # nada pra buscar sem nenhuma candidata


def test_recalcular_tarefa_sem_data_de_conclusao_fica_fora(app):
    _depara(conta="95", id_auvo=13804973)
    tarefa_sem_data = _tarefa(13804973, None)
    auvo = FakeAuvoClient(tarefas=[tarefa_sem_data])

    run = bi_service.recalcular(
        config=app.config,
        periodo_desde=AGORA - timedelta(days=90),
        periodo_hasta=AGORA,
        auvo_client=auvo,
        softguard_client=FakeSoftGuardClient(),
    )

    assert run.status == "success"
    assert run.resumo["sem_data"] == 1
    assert run.resumo["total_intervencoes"] == 0


def test_recalcular_ignora_tarefa_nao_concluida(app):
    _depara(conta="95", id_auvo=13804973)
    auvo = FakeAuvoClient(tarefas=[_tarefa(13804973, MARCO_FECHADO, finished=False, task_status=3)])

    run = bi_service.recalcular(
        config=app.config,
        periodo_desde=AGORA - timedelta(days=90),
        periodo_hasta=AGORA,
        auvo_client=auvo,
        softguard_client=FakeSoftGuardClient(),
    )

    assert run.resumo["total_intervencoes"] == 0
    assert run.resumo["sem_vinculo"] == 0
    assert run.resumo["sem_data"] == 0


def test_recalcular_filtra_por_tecnico(app):
    _depara(conta="95", id_auvo=13804973)
    auvo = FakeAuvoClient(tarefas=[_tarefa(13804973, MARCO_FECHADO, tecnico="Henrique Souza")])

    run = bi_service.recalcular(
        config=app.config,
        periodo_desde=AGORA - timedelta(days=90),
        periodo_hasta=AGORA,
        tecnico="Alfredo",
        auvo_client=auvo,
        softguard_client=FakeSoftGuardClient(),
    )

    assert run.resumo["total_intervencoes"] == 0


def test_recalcular_filtra_por_tipo_de_intervencao(app):
    _depara(conta="95", id_auvo=13804973)
    settings_service.set("bi_tipos_intervencao", "999999")
    db.session.commit()
    auvo = FakeAuvoClient(tarefas=[_tarefa(13804973, MARCO_FECHADO, task_type=145696)])

    run = bi_service.recalcular(
        config=app.config,
        periodo_desde=AGORA - timedelta(days=90),
        periodo_hasta=AGORA,
        auvo_client=auvo,
        softguard_client=FakeSoftGuardClient(),
    )

    assert run.resumo["total_intervencoes"] == 0


def test_recalcular_marca_erro_sem_derrubar_quando_sem_credenciais(app):
    auvo_indisponivel = None  # sem auvo_client e sem credenciais configuradas -> criar_cliente None

    run = bi_service.recalcular(
        config=app.config,
        periodo_desde=AGORA - timedelta(days=90),
        periodo_hasta=AGORA,
        auvo_client=auvo_indisponivel,
        softguard_client=FakeSoftGuardClient(),
    )

    assert run.status == "error"
    assert "credenciais" in run.erro_mensagem.lower()
    assert BiRun.query.count() == 1  # o run fica registrado mesmo com erro


def test_recalcular_bloqueia_execucao_concorrente(app):
    assert bi_service._lock_recalculo.acquire(blocking=False) is True
    try:
        with pytest.raises(bi_service.BiRecalculoEmAndamentoError):
            bi_service.recalcular(
                config=app.config,
                periodo_desde=AGORA - timedelta(days=90),
                periodo_hasta=AGORA,
                auvo_client=FakeAuvoClient(),
                softguard_client=FakeSoftGuardClient(),
            )
    finally:
        bi_service._lock_recalculo.release()


# ---------- agregações ----------


def test_resumo_por_tecnico_e_clientes_cronicos_leem_do_run(app):
    _depara(conta="95", id_auvo=13804973)
    marcos = [MARCO_FECHADO - timedelta(days=40), MARCO_FECHADO - timedelta(days=20), MARCO_FECHADO]
    tarefas = [_tarefa(13804973, marco) for marco in marcos]
    eventos = []
    for marco in marcos:
        eventos += _eventos_melhorou(conta="0095", marco=marco)

    run = bi_service.recalcular(
        config=app.config,
        periodo_desde=AGORA - timedelta(days=90),
        periodo_hasta=AGORA,
        auvo_client=FakeAuvoClient(tarefas=tarefas),
        softguard_client=FakeSoftGuardClient(eventos=eventos),
    )
    assert run.status == "success"
    assert run.resumo["total_intervencoes"] == 3

    resumo = bi_service.resumo_por_tecnico(run)
    assert len(resumo) == 1
    assert resumo[0].tecnico == "Alfredo Silva"
    assert resumo[0].total_intervencoes == 3

    cronicos = bi_service.clientes_cronicos(run)
    # 3 visitas e ainda com disparo (mesmo que reduzido) na mais recente -> crônico
    assert len(cronicos) == 1
    assert cronicos[0].conta_power == "95"
    assert cronicos[0].total_visitas == 3


def test_ultimo_run_e_carregar_run(app):
    _depara(conta="95", id_auvo=13804973)
    run = bi_service.recalcular(
        config=app.config,
        periodo_desde=AGORA - timedelta(days=90),
        periodo_hasta=AGORA,
        auvo_client=FakeAuvoClient(tarefas=[_tarefa(13804973, MARCO_FECHADO)]),
        softguard_client=FakeSoftGuardClient(eventos=_eventos_melhorou()),
    )

    assert bi_service.ultimo_run().id == run.id
    assert bi_service.carregar_run(run.id).id == run.id
    assert bi_service.carregar_run(999999) is None
