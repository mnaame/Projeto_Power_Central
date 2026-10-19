"""Contas em teste em lote — o módulo que SUPRIME ALARME.

Os testes aqui valem como os do ajuste de horário: um erro não quebra uma
tela, tira a cobertura de uma loja — e o estrago só aparece se alguém
tentar entrar nela.
"""

import pytest

from app.extensions import db
from app.integrations.softguard_client import SoftGuardError
from app.services import contas_teste_service as svc
from app.services import settings_service

MENSAGEM = "420 SN. FLEMING\n688 SN. CASTELO\n530 AP. VENDA NOVA"

CONTAS = [
    {"cue_iid": "9001", "cue_ncuenta": "0002", "cue_cnombre": "SUPER NOSSO FLEMING FILIAL 420"},
    {"cue_iid": "9002", "cue_ncuenta": "0010", "cue_cnombre": "SUPER NOSSO (CASTELO FILIAL 688)"},
    {"cue_iid": "9003", "cue_ncuenta": "0011", "cue_cnombre": "APOIO (VENDA NOVA FILIAL 530)"},
    # A tesouraria é conta separada da loja e NUNCA entra em teste.
    {"cue_iid": "9006", "cue_ncuenta": "0327", "cue_cnombre": "SUPER NOSSO CASTELO TESOURARIA"},
    {"cue_iid": "9007", "cue_ncuenta": "0330", "cue_cnombre": "SUPER NOSSO CASTELO LOJA"},
    # Base e Villefort entram na lista do portal, mas NÃO são elegíveis.
    {"cue_iid": "9004", "cue_ncuenta": "0420", "cue_cnombre": "PADARIA DO ZE 420"},
    {"cue_iid": "9005", "cue_ncuenta": "0030", "cue_cnombre": "VILLEFORT TROPICAL 688"},
]


class FakePortal:
    def __init__(self, contas=None, *, erro_em=None, erro_contas=None):
        self.contas = CONTAS if contas is None else contas
        self.erro_em = erro_em or set()
        self.erro_contas = erro_contas
        self.gravacoes = []

    def listar_todas_contas(self, **kwargs):
        if self.erro_contas:
            raise self.erro_contas
        return self.contas

    def colocar_em_teste(self, cue_iid, *, inicio, dias, nota, tipo=3):
        if str(cue_iid) in self.erro_em:
            raise SoftGuardError("a plataforma recusou")
        self.gravacoes.append(
            {"cue_iid": str(cue_iid), "inicio": inicio, "dias": dias, "nota": nota, "tipo": tipo}
        )
        return {"success": True}


# ---------- preparar: NÃO escreve ----------


def test_preparar_nao_escreve_nada(app):
    portal = FakePortal()

    svc.preparar(MENSAGEM, config=app.config, softguard_client=portal)

    assert portal.gravacoes == []


def test_preparar_casa_as_filiais_da_mensagem(app):
    preview = svc.preparar(MENSAGEM, config=app.config, softguard_client=FakePortal())

    assert [c.conta.numero for c in preview["casados"]] == ["0002", "0010", "0011"]


def test_so_super_nosso_e_apoio_sao_elegiveis(app):
    """Um número de filial solto casaria com qualquer conta da base que
    tivesse esse número no nome. Limitar ao grupo que manda a lista é o
    que impede um erro de digitação de alcançar a padaria da esquina."""
    preview = svc.preparar("420", config=app.config, softguard_client=FakePortal())

    assert [c.conta.nome for c in preview["casados"]] == ["SUPER NOSSO FLEMING FILIAL 420"]
    # 3 do grupo + a CASTELO LOJA; a tesouraria fica fora.
    assert preview["elegiveis"] == 4


def test_filial_desconhecida_fica_visivel(app):
    preview = svc.preparar(
        "420\n777", config=app.config, softguard_client=FakePortal()
    )

    assert [c.filial for c in preview["nao_encontrados"]] == ["777"]


def test_mensagem_sem_numero_avisa_em_vez_de_preparar_lote_vazio(app):
    with pytest.raises(svc.ContasTesteError, match="número de filial"):
        svc.preparar("bom dia, segue em anexo", config=app.config,
                     softguard_client=FakePortal())


def test_janela_de_segunda_a_sexta_por_padrao(app):
    """5 dias. O serviço noturno é de dia útil; cobrir sábado e domingo
    suprimiria alarme em dois dias nos quais ninguém pediu isso."""
    preview = svc.preparar(MENSAGEM, config=app.config, softguard_client=FakePortal())

    assert preview["dias"] == 5
    assert (preview["fim"] - preview["inicio"]).days == 5


def test_portal_fora_do_ar_aborta_com_erro_proprio(app):
    portal = FakePortal(erro_contas=SoftGuardError("portal fora"))

    with pytest.raises(svc.ContasTesteError, match="portal fora"):
        svc.preparar(MENSAGEM, config=app.config, softguard_client=portal)


# ---------- aplicar: ESCREVE ----------


def test_aplicar_grava_as_contas_confirmadas(app, admin_user):
    portal = FakePortal()

    resultado = svc.aplicar(
        ["9001", "9002"], config=app.config, user=admin_user, softguard_client=portal
    )
    db.session.commit()

    assert [g["cue_iid"] for g in portal.gravacoes] == ["9001", "9002"]
    assert resultado["aplicados"] == ["9001", "9002"]


def test_aplicar_usa_a_janela_e_a_nota_configuradas(app, admin_user):
    portal = FakePortal()

    svc.aplicar(["9001"], config=app.config, user=admin_user, softguard_client=portal)
    db.session.commit()

    gravado = portal.gravacoes[0]
    assert gravado["dias"] == 5
    assert gravado["tipo"] == 3
    assert "noturno" in gravado["nota"]


def test_falha_numa_conta_nao_derruba_as_outras(app, admin_user):
    """Metade do lote aplicado e dito às claras é melhor que um erro
    genérico que não diz quais entraram."""
    portal = FakePortal(erro_em={"9002"})

    resultado = svc.aplicar(
        ["9001", "9002", "9003"], config=app.config, user=admin_user,
        softguard_client=portal,
    )
    db.session.commit()

    assert resultado["aplicados"] == ["9001", "9003"]
    assert resultado["falhas"][0]["cue_iid"] == "9002"
    assert "recusou" in resultado["falhas"][0]["erro"]


def test_lista_vazia_e_recusada(app, admin_user):
    with pytest.raises(svc.ContasTesteError, match="Nenhuma conta"):
        svc.aplicar([], config=app.config, user=admin_user, softguard_client=FakePortal())


def test_duracao_invalida_nao_grava_nada(app, admin_user):
    """A janela é a única coisa que impede uma conta de ficar silenciada
    para sempre."""
    settings_service.set("teste_duracao_dias", "0")
    db.session.commit()
    portal = FakePortal()

    with pytest.raises(ValueError):
        svc.aplicar(["9001"], config=app.config, user=admin_user, softguard_client=portal)

    assert portal.gravacoes == []


def test_lote_e_auditado_so_com_contagens(app, admin_user):
    from app.models.audit import AuditLog

    portal = FakePortal(erro_em={"9002"})

    svc.aplicar(
        ["9001", "9002"], config=app.config, user=admin_user, softguard_client=portal
    )
    db.session.commit()

    entrada = AuditLog.query.filter_by(action="contas_teste_lote").one()
    assert entrada.result == "failure"  # houve falha no lote
    assert entrada.details["aplicadas"] == 1
    assert entrada.details["falhas"] == 1
    assert entrada.details["dias"] == 5
    assert "SUPER NOSSO" not in str(entrada.details)


# ---------- tesouraria: nunca entra ----------


def test_tesouraria_fica_fora_dos_elegiveis(app):
    elegiveis, barradas = svc.contas_do_super_nosso(CONTAS)

    assert [c.numero for c in barradas] == ["0327"]
    assert "0327" not in [c.numero for c in elegiveis]


def test_tesouraria_aparece_na_previsualizacao_em_vez_de_sumir(app):
    """Exclusão silenciosa é indistinguível de esquecimento."""
    preview = svc.preparar("420", config=app.config, softguard_client=FakePortal())

    assert [c.nome for c in preview["barradas"]] == ["SUPER NOSSO CASTELO TESOURARIA"]


def test_tesouraria_com_numero_de_filial_continua_barrada(app):
    """Hoje nenhuma tesouraria tem número de filial no nome — mas isso é
    uma propriedade do cadastro de hoje, não uma garantia. Basta alguém
    renomear a conta e a sorte acaba."""
    contas = [
        {"cue_iid": "9100", "cue_ncuenta": "0327",
         "cue_cnombre": "SUPER NOSSO CASTELO TESOURARIA FILIAL 688"},
    ]

    preview = svc.preparar("688", config=app.config,
                           softguard_client=FakePortal(contas))

    assert preview["casados"] == []
    assert [c.filial for c in preview["nao_encontrados"]] == ["688"]


def test_tesouraria_e_barrada_tambem_na_hora_de_gravar(app, admin_user):
    """Segunda barreira, já na beira da escrita: a primeira depende de o
    lote ter vindo de uma pré-visualização íntegra, esta não depende de
    nada."""
    portal = FakePortal()

    resultado = svc.aplicar(
        ["9001", "9006"], config=app.config, user=admin_user, softguard_client=portal
    )
    db.session.commit()

    assert [g["cue_iid"] for g in portal.gravacoes] == ["9001"]
    assert resultado["bloqueadas"] == ["9006"]


def test_lote_so_de_tesouraria_nao_grava_nada(app, admin_user):
    portal = FakePortal()

    with pytest.raises(svc.ContasTesteError, match="tesouraria"):
        svc.aplicar(["9006"], config=app.config, user=admin_user,
                    softguard_client=portal)

    assert portal.gravacoes == []
