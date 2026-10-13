"""Ajuste de horário em lote — o módulo que ESCREVE na plataforma.

Os testes aqui valem mais que os de qualquer outro módulo: um erro não
quebra uma tela, desregula a supervisão da base inteira, e o estrago só
aparece dias depois quando um "não abriu" deixar de ser disparado.
"""

from app.extensions import db
from app.integrations.softguard_client import SoftGuardError
from app.models.horario_lote import AjusteHorarioItem
from app.services import horario_lote_service as svc
from app.services import settings_service

CONTAS = [
    {"cue_iid": "9383", "cue_ncuenta": "0118", "cue_cnombre": "SHOPPING VETTORE"},
    {"cue_iid": "9400", "cue_ncuenta": "0095", "cue_cnombre": "AUTO MECANICA"},
]


def _horario(horario_id, cue_iid, fechamento, dia=7):
    return {
        "Id": horario_id,
        "Name": "",
        "hor_iidcuenta": int(cue_iid),
        "hor_ndiaapertura": dia,
        "hor_choraapertura": "06:00",
        "hor_ndiacierre": dia,
        "hor_choracierre": fechamento,
    }


class FakePortal:
    """Guarda o estado como a plataforma guardaria: o PUT muda o valor, e
    a leitura seguinte vê o valor mudado."""

    def __init__(self, horarios=None, *, erro_no_put=None, erro_na_leitura=None):
        self.horarios = horarios if horarios is not None else {
            "9383": [_horario(7201, "9383", "18:00"), _horario(7202, "9383", "23:00")],
            "9400": [_horario(7301, "9400", "19:30")],
        }
        self.erro_no_put = erro_no_put or {}
        self.erro_na_leitura = erro_na_leitura or set()
        self.puts = []
        self.leituras = 0

    def listar_todas_contas(self, **kwargs):
        return CONTAS

    def listar_horarios(self, cue_iid, **kwargs):
        chave = str(cue_iid)
        self.leituras += 1
        if chave in self.erro_na_leitura:
            raise SoftGuardError("portal recusou a leitura")
        return [dict(linha) for linha in self.horarios.get(chave, [])]

    def atualizar_horario(self, corpo):
        identificador = str(corpo["Id"])
        if identificador in self.erro_no_put:
            raise SoftGuardError(self.erro_no_put[identificador])
        self.puts.append(dict(corpo))
        for linhas in self.horarios.values():
            for linha in linhas:
                if str(linha["Id"]) == identificador:
                    linha["hor_choracierre"] = corpo["hor_choracierre"]
        return corpo


def _preparar(app, portal):
    lote = svc.preparar(config=app.config, softguard_client=portal)
    db.session.commit()
    return lote


# ---------- preparação ----------


def test_preparar_nao_escreve_nada(app):
    portal = FakePortal()

    _preparar(app, portal)

    assert portal.puts == []


def test_preparar_separa_aplicar_de_manual(app):
    lote = _preparar(app, FakePortal())

    aplicar = svc.itens(lote, categoria="aplicar")
    manual = svc.itens(lote, categoria="manual")

    assert [(i.antes, i.depois) for i in aplicar] == [("18:00", "19:00"), ("19:30", "20:30")]
    assert [(i.antes, i.depois) for i in manual] == [("23:00", "")]


def test_preparar_guarda_o_estado_antes_para_o_backup(app):
    lote = _preparar(app, FakePortal())

    assert sorted(i.antes for i in svc.itens(lote)) == ["18:00", "19:30", "23:00"]


def test_conta_que_falha_na_leitura_nao_derruba_a_varredura(app):
    portal = FakePortal(erro_na_leitura={"9383"})

    lote = _preparar(app, portal)

    assert [i.conta for i in svc.itens(lote)] == ["0095"]
    assert lote.contas_varridas == 1


# ---------- simulação ----------


def test_simulacao_ligada_por_padrao_nao_grava(app, admin_user):
    portal = FakePortal()
    lote = _preparar(app, portal)
    assert lote.simulacao is True

    contagem = svc.aplicar(lote, config=app.config, user=admin_user, softguard_client=portal)
    db.session.commit()

    assert portal.puts == []
    assert contagem["simulado"] == 2
    # Simulado continua pendente: a execução real ainda tem o que fazer.
    assert lote.itens.filter(AjusteHorarioItem.status == "simulado").count() == 2


def test_com_simulacao_desligada_grava_de_verdade(app, admin_user):
    settings_service.set("horario_lote_simulacao", "false")
    db.session.commit()
    portal = FakePortal()
    lote = _preparar(app, portal)

    svc.aplicar(lote, config=app.config, user=admin_user, softguard_client=portal)
    db.session.commit()

    assert [p["hor_choracierre"] for p in portal.puts] == ["19:00", "20:30"]
    assert lote.status == "aplicado"


def test_so_o_fechamento_muda_no_put(app, admin_user):
    settings_service.set("horario_lote_simulacao", "false")
    db.session.commit()
    portal = FakePortal()
    lote = _preparar(app, portal)

    svc.aplicar(lote, config=app.config, user=admin_user, softguard_client=portal)

    enviado = next(p for p in portal.puts if p["Id"] == 7201)
    assert enviado["hor_choraapertura"] == "06:00"
    assert enviado["hor_ndiaapertura"] == 7
    assert enviado["hor_ndiacierre"] == 7
    assert enviado["hor_choracierre"] == "19:00"


def test_linha_que_vira_meia_noite_nunca_e_enviada(app, admin_user):
    settings_service.set("horario_lote_simulacao", "false")
    db.session.commit()
    portal = FakePortal()
    lote = _preparar(app, portal)

    svc.aplicar(lote, config=app.config, user=admin_user, softguard_client=portal)

    assert all(str(p["Id"]) != "7202" for p in portal.puts)
    assert portal.horarios["9383"][1]["hor_choracierre"] == "23:00"  # intacto


# ---------- idempotência: a trava que impede somar 2h ----------


def test_rodar_duas_vezes_nao_soma_de_novo(app, admin_user):
    """A falha mais cara possível deste módulo."""
    settings_service.set("horario_lote_simulacao", "false")
    db.session.commit()
    portal = FakePortal()
    lote = _preparar(app, portal)

    svc.aplicar(lote, config=app.config, user=admin_user, softguard_client=portal)
    db.session.commit()
    puts_primeira = len(portal.puts)

    svc.aplicar(lote, config=app.config, user=admin_user, softguard_client=portal)
    db.session.commit()

    assert len(portal.puts) == puts_primeira  # nenhum PUT a mais
    assert portal.horarios["9383"][0]["hor_choracierre"] == "19:00"  # não virou 20:00


def test_lote_preparado_duas_vezes_detecta_que_ja_foi_aplicado(app, admin_user):
    """Preparar de novo depois de aplicar: o novo lote veria 19:00 e
    proporia 20:00. Mas o item que JÁ está no destino do lote anterior
    não pode ser somado de novo sem decisão humana — aqui o segundo lote
    é legítimo (o admin pediu outro +1h), e o teste documenta isso."""
    settings_service.set("horario_lote_simulacao", "false")
    db.session.commit()
    portal = FakePortal()
    primeiro = _preparar(app, portal)
    svc.aplicar(primeiro, config=app.config, user=admin_user, softguard_client=portal)
    db.session.commit()

    segundo = _preparar(app, portal)

    assert [(i.antes, i.depois) for i in svc.itens(segundo, categoria="aplicar")] == [
        ("19:00", "20:00"), ("20:30", "21:30")
    ]


def test_valor_ja_no_destino_e_pulado(app, admin_user):
    """Alguém ajustou à mão para 19:00 antes de o lote rodar."""
    settings_service.set("horario_lote_simulacao", "false")
    db.session.commit()
    portal = FakePortal()
    lote = _preparar(app, portal)
    portal.horarios["9383"][0]["hor_choracierre"] = "19:00"

    contagem = svc.aplicar(lote, config=app.config, user=admin_user, softguard_client=portal)
    db.session.commit()

    assert contagem.get("ja_aplicado") == 1
    assert all(str(p["Id"]) != "7201" for p in portal.puts)


def test_valor_diferente_do_previsto_nao_e_tocado(app, admin_user):
    """Alguém mexeu no horário entre preparar e aplicar: não se escreve
    por cima do trabalho de outra pessoa."""
    settings_service.set("horario_lote_simulacao", "false")
    db.session.commit()
    portal = FakePortal()
    lote = _preparar(app, portal)
    portal.horarios["9383"][0]["hor_choracierre"] = "17:00"

    contagem = svc.aplicar(lote, config=app.config, user=admin_user, softguard_client=portal)
    db.session.commit()

    assert contagem.get("divergente") == 1
    assert portal.horarios["9383"][0]["hor_choracierre"] == "17:00"
    item = lote.itens.filter(AjusteHorarioItem.status == "divergente").one()
    assert "17:00" in item.erro_mensagem


def test_horario_que_sumiu_do_portal_vira_divergente(app, admin_user):
    settings_service.set("horario_lote_simulacao", "false")
    db.session.commit()
    portal = FakePortal()
    lote = _preparar(app, portal)
    portal.horarios["9383"] = []

    contagem = svc.aplicar(lote, config=app.config, user=admin_user, softguard_client=portal)
    db.session.commit()

    assert contagem.get("divergente") == 1


# ---------- falha isolada e teste em uma conta ----------


def test_falha_num_put_nao_derruba_as_outras_linhas(app, admin_user):
    settings_service.set("horario_lote_simulacao", "false")
    db.session.commit()
    portal = FakePortal(erro_no_put={"7201": "portal recusou"})
    lote = _preparar(app, portal)

    contagem = svc.aplicar(lote, config=app.config, user=admin_user, softguard_client=portal)
    db.session.commit()

    assert contagem.get("erro") == 1
    assert contagem.get("aplicado") == 1  # a outra conta passou
    assert lote.status == "parcial"


def test_aplicar_em_uma_conta_so_nao_toca_nas_outras(app, admin_user):
    settings_service.set("horario_lote_simulacao", "false")
    db.session.commit()
    portal = FakePortal()
    lote = _preparar(app, portal)

    svc.aplicar(
        lote, config=app.config, user=admin_user,
        apenas_conta="0118", softguard_client=portal,
    )
    db.session.commit()

    assert [str(p["Id"]) for p in portal.puts] == ["7201"]
    assert portal.horarios["9400"][0]["hor_choracierre"] == "19:30"  # intacta


def test_releitura_acontece_uma_vez_por_conta_e_nao_por_linha(app, admin_user):
    """A proteção é por linha, mas o custo não pode ser: uma requisição
    por linha multiplicaria a operação por sete."""
    settings_service.set("horario_lote_simulacao", "false")
    db.session.commit()
    portal = FakePortal()
    lote = _preparar(app, portal)
    leituras_apos_preparar = portal.leituras

    svc.aplicar(lote, config=app.config, user=admin_user, softguard_client=portal)

    assert portal.leituras - leituras_apos_preparar == 2  # duas contas, não três linhas


# ---------- auditoria ----------


def test_cada_alteracao_e_auditada_com_antes_e_depois(app, admin_user):
    from app.models.audit import AuditLog

    settings_service.set("horario_lote_simulacao", "false")
    db.session.commit()
    portal = FakePortal()
    lote = _preparar(app, portal)

    svc.aplicar(lote, config=app.config, user=admin_user, softguard_client=portal)
    db.session.commit()

    entradas = AuditLog.query.filter_by(action="horario_lote_ajuste").all()
    assert len(entradas) == 2
    assert all(len(e.action) <= 48 for e in entradas)
    uma = next(e for e in entradas if e.details["horario_id"] == "7201")
    assert uma.details["antes"] == "18:00"
    assert uma.details["depois"] == "19:00"


def test_simulacao_nao_gera_auditoria_de_alteracao(app, admin_user):
    from app.models.audit import AuditLog

    portal = FakePortal()
    lote = _preparar(app, portal)

    svc.aplicar(lote, config=app.config, user=admin_user, softguard_client=portal)
    db.session.commit()

    assert AuditLog.query.filter_by(action="horario_lote_ajuste").count() == 0
    assert AuditLog.query.filter_by(action="horario_lote_execucao").count() == 1


# ---------- o teste em uma conta ----------


def test_conta_sem_os_zeros_da_frente_e_a_mesma_conta(app, admin_user):
    """"118" e "0118" são a mesma conta — e o exemplo do próprio campo
    mandava digitar sem os zeros. A comparação era exata: o filtro não
    casava com nada, nenhuma linha era tocada, e a tela respondia "0
    linha(s)" como se o módulo não funcionasse."""
    settings_service.set("horario_lote_simulacao", "false")
    db.session.commit()
    portal = FakePortal()
    lote = _preparar(app, portal)

    svc.aplicar(
        lote, config=app.config, user=admin_user,
        apenas_conta="118", softguard_client=portal,
    )
    db.session.commit()

    assert [str(p["Id"]) for p in portal.puts] == ["7201"]


def test_conta_que_nao_esta_no_lote_avisa_em_vez_de_dizer_zero(app, admin_user):
    """"0 linha(s)" é indistinguível de "o módulo não funciona"."""
    portal = FakePortal()
    lote = _preparar(app, portal)

    try:
        svc.aplicar(
            lote, config=app.config, user=admin_user,
            apenas_conta="9999", softguard_client=portal,
        )
    except svc.HorarioLoteError as exc:
        assert "9999" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("deveria ter avisado que a conta não está no lote")


def test_teste_em_uma_conta_grava_de_verdade_mesmo_em_simulacao(app, admin_user):
    """Sem isto, o passo 3 do caminho seguro ("teste em 1 conta e confira
    na plataforma") só era possível desarmando a chave global — que arma
    o botão do lote inteiro junto."""
    portal = FakePortal()
    lote = _preparar(app, portal)
    assert settings_service.horario_lote_simulacao() is True

    svc.aplicar(
        lote, config=app.config, user=admin_user,
        apenas_conta="0118", gravar_de_verdade=True, softguard_client=portal,
    )
    db.session.commit()

    assert [str(p["Id"]) for p in portal.puts] == ["7201"]
    assert portal.horarios["9400"][0]["hor_choracierre"] == "19:30"  # a outra, intacta


def test_gravar_de_verdade_sem_conta_nao_libera_o_lote_inteiro(app, admin_user):
    """A liberação é para UMA conta. No lote inteiro quem manda continua
    sendo a chave de Configurações."""
    portal = FakePortal()
    lote = _preparar(app, portal)

    svc.aplicar(
        lote, config=app.config, user=admin_user,
        apenas_conta="", gravar_de_verdade=True, softguard_client=portal,
    )
    db.session.commit()

    assert portal.puts == []


def test_simulacao_vale_a_do_momento_da_execucao_e_nao_a_do_preparo(app, admin_user):
    """A simulação não é propriedade do lote: o preparo só lê. Lendo do
    lote, desligar a chave não surtia efeito sem repreparar tudo — uma
    varredura de minutos — e a tela mostrava "Aplicar" enquanto o código
    simulava calado."""
    portal = FakePortal()
    lote = _preparar(app, portal)
    assert lote.simulacao is True

    settings_service.set("horario_lote_simulacao", "false")
    db.session.commit()

    svc.aplicar(lote, config=app.config, user=admin_user, softguard_client=portal)
    db.session.commit()

    assert len(portal.puts) == 2
    assert lote.simulacao is False  # o histórico guarda o que de fato houve
