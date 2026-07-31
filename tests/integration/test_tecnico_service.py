from datetime import date, datetime, timezone

import pytest

from app.extensions import db
from app.integrations.softguard_client import SoftGuardError
from app.models.auvo import AuvoDepara
from app.services import tecnico_service


class FakeAuvoClient:
    def __init__(self, tarefas=None):
        self.tarefas = tarefas or []
        self.chamadas = []

    def listar_tarefas(self, data_inicio, data_fim):
        self.chamadas.append((data_inicio, data_fim))
        return self.tarefas


class FakeSoftGuardClient:
    def __init__(self, contas=None, historico=None, recusar_contas=None):
        self.contas = contas or []
        self.historico = historico or {}  # numero_conta -> bytes | Exception
        self.chamadas_export = []

    def listar_todas_contas(self, **kwargs):
        return self.contas

    def exportar_historico_html(self, *, numero_conta, **kwargs):
        self.chamadas_export.append({"numero_conta": numero_conta, **kwargs})
        resultado = self.historico.get(numero_conta)
        if isinstance(resultado, Exception):
            raise resultado
        return resultado or b"<html><table><tr><td>Historico</td></tr></table></html>"


def _tarefa(customer_id, tecnico="Alfredo Silva", nome=None):
    return {
        "customerId": customer_id,
        "userToName": tecnico,
        "customerDescription": nome or f"Cliente {customer_id}",
        "taskDate": "2026-07-31T08:00:00",
    }


def _depara(conta, id_auvo, status="OK", nome="Loja Teste"):
    linha = AuvoDepara(
        conta_power=conta, id_auvo=id_auvo, status=status, nome_power=nome
    )
    db.session.add(linha)
    db.session.commit()
    return linha


# ---------- buscar_agenda ----------


def test_buscar_agenda_filtra_por_tecnico_e_cruza_depara(app):
    _depara("95", 13804973, nome="CLINICA KENNEDY")
    auvo = FakeAuvoClient(
        tarefas=[
            _tarefa(13804973, tecnico="Alfredo Silva"),
            _tarefa(13804999, tecnico="Henrique Souza"),  # técnico diferente
        ]
    )

    itens = tecnico_service.buscar_agenda(
        config={}, data=date(2026, 7, 31), tecnico="Alfredo", client=auvo
    )

    assert len(itens) == 1
    assert itens[0].conta_power == "95"
    assert itens[0].nome_conta == "CLINICA KENNEDY"
    assert itens[0].tem_depara is True
    assert auvo.chamadas == [("2026-07-31", "2026-07-31")]


def test_buscar_agenda_marca_sem_depara_quando_nao_ha_vinculo(app):
    auvo = FakeAuvoClient(tarefas=[_tarefa(999999, tecnico="Alfredo")])

    itens = tecnico_service.buscar_agenda(
        config={}, data=date(2026, 7, 31), tecnico="", client=auvo
    )

    assert len(itens) == 1
    assert itens[0].tem_depara is False
    assert itens[0].conta_power is None


def test_buscar_agenda_ignora_depara_em_revisao(app):
    _depara("95", 13804973, status="REVISAR")
    auvo = FakeAuvoClient(tarefas=[_tarefa(13804973)])

    itens = tecnico_service.buscar_agenda(config={}, data=date(2026, 7, 31), tecnico="", client=auvo)

    assert itens[0].tem_depara is False


def test_buscar_agenda_sem_credenciais_levanta_erro(app):
    with pytest.raises(tecnico_service.TecnicoAgendaError):
        tecnico_service.buscar_agenda(config=app.config, data=date(2026, 7, 31), tecnico="", client=None)


# ---------- criar_lote ----------


def test_criar_lote_vazio_levanta_erro(app):
    with pytest.raises(tecnico_service.TecnicoLoteVazioError):
        tecnico_service.criar_lote(
            selecionadas=[],
            data_agenda=date(2026, 7, 31),
            tecnico_id_auvo=None,
            tecnico_nome="Alfredo",
            periodo_desde=datetime(2026, 7, 1, tzinfo=timezone.utc),
            periodo_hasta=datetime(2026, 7, 31, tzinfo=timezone.utc),
            codigos_globais=("CLO", "OPN"),
            user_id=None,
        )


def test_criar_lote_persiste_itens_com_override_de_codigos(app):
    lote = tecnico_service.criar_lote(
        selecionadas=[
            {"conta_power": "95", "nome_loja": "CLINICA KENNEDY"},
            {"conta_power": "4", "nome_loja": "VILLEFORT TROPICAL", "codigos": ["CLO", "OPN", "BUR"]},
        ],
        data_agenda=date(2026, 7, 31),
        tecnico_id_auvo=159336,
        tecnico_nome="Alfredo Silva",
        periodo_desde=datetime(2026, 7, 1, tzinfo=timezone.utc),
        periodo_hasta=datetime(2026, 7, 31, tzinfo=timezone.utc),
        codigos_globais=("CLO", "OPN", "BYP"),
        user_id=None,
    )

    assert lote.status == "running"
    assert len(lote.itens) == 2
    assert lote.itens[0].codigos_usados == ["CLO", "OPN", "BYP"]
    assert lote.itens[1].codigos_usados == ["CLO", "OPN", "BUR"]
    assert all(item.status == "pendente" for item in lote.itens)


# ---------- gerar_lote ----------


def _criar_lote_simples(*, contas):
    return tecnico_service.criar_lote(
        selecionadas=[{"conta_power": conta, "nome_loja": f"Loja {conta}"} for conta in contas],
        data_agenda=date(2026, 7, 31),
        tecnico_id_auvo=None,
        tecnico_nome="Alfredo",
        periodo_desde=datetime(2026, 7, 1, tzinfo=timezone.utc),
        periodo_hasta=datetime(2026, 7, 31, tzinfo=timezone.utc),
        codigos_globais=("CLO", "OPN"),
        user_id=None,
    )


def test_gerar_lote_falha_isolada_por_loja(app):
    lote = _criar_lote_simples(contas=["95", "4", "999"])  # 999 não existe na PowerCentral

    softguard = FakeSoftGuardClient(
        contas=[
            {"cue_ncuenta": "0095", "cue_iid": "9385", "cue_cnombre": "CLINICA KENNEDY"},
            {"cue_ncuenta": "0004", "cue_iid": "4021", "cue_cnombre": "VILLEFORT TROPICAL"},
        ],
        historico={"4": SoftGuardError("A PowerCentral recusou o export.")},
    )

    resultado = tecnico_service.gerar_lote(lote=lote, config={}, softguard_client=softguard)

    itens_por_conta = {item.conta_power: item for item in resultado.itens}
    assert itens_por_conta["95"].status == "gerado"
    assert itens_por_conta["95"].arquivo_path is not None
    assert itens_por_conta["4"].status == "erro"
    assert "recusou" in itens_por_conta["4"].erro_mensagem
    assert itens_por_conta["999"].status == "erro"
    assert itens_por_conta["999"].erro_mensagem == "Conta não encontrada na PowerCentral."
    assert resultado.status == "parcial"


def test_gerar_lote_todos_com_sucesso(app):
    lote = _criar_lote_simples(contas=["95"])
    softguard = FakeSoftGuardClient(
        contas=[{"cue_ncuenta": "0095", "cue_iid": "9385", "cue_cnombre": "CLINICA KENNEDY"}]
    )

    resultado = tecnico_service.gerar_lote(lote=lote, config={}, softguard_client=softguard)

    assert resultado.status == "success"
    assert softguard.chamadas_export[0]["numero_conta"] == "95"
    assert softguard.chamadas_export[0]["cue_iid"] == "9385"


def test_gerar_lote_bloqueia_segunda_execucao_do_mesmo_lote(app):
    lote = _criar_lote_simples(contas=["95"])
    assert tecnico_service.tentar_iniciar_execucao(lote.id) is True
    try:
        with pytest.raises(tecnico_service.TecnicoLoteEmAndamentoError):
            tecnico_service.gerar_lote(lote=lote, config={}, softguard_client=FakeSoftGuardClient())
    finally:
        tecnico_service.finalizar_execucao(lote.id)


# ---------- montar_zip ----------


def test_montar_zip_so_inclui_itens_gerados(app):
    import zipfile

    lote = _criar_lote_simples(contas=["95", "4"])
    softguard = FakeSoftGuardClient(
        contas=[{"cue_ncuenta": "0095", "cue_iid": "9385", "cue_cnombre": "CLINICA KENNEDY"}],
    )
    tecnico_service.gerar_lote(lote=lote, config={}, softguard_client=softguard)

    caminho_zip = tecnico_service.montar_zip(lote)

    with zipfile.ZipFile(caminho_zip) as zipf:
        nomes = zipf.namelist()
    assert len(nomes) == 1
    assert "0095" in nomes[0]
