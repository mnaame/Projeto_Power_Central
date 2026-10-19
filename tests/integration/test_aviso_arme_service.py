"""Lojas sem arme — desliga o aviso de "não armou", sem cegar a conta.

Os testes aqui valem como os do ajuste de horário: um erro não quebra uma
tela, tira a supervisão de arme de uma loja. A diferença para o mecanismo
anterior (conta em teste) é que o disparo continua chegando — mas uma
loja sem aviso de arme ainda é uma loja que ninguém vai cobrar se não
fechar.

E este mecanismo **não expira sozinho**: o que impede uma conta de ficar
desligada para sempre é o ledger e o ciclo semanal.
"""

import pytest

from app.extensions import db
from app.integrations.softguard_client import SoftGuardError
from app.models.aviso_arme import AvisoArmeDesligado
from app.services import aviso_arme_service as svc

MENSAGEM = "420 SN. FLEMING\n688 SN. CASTELO\n530 AP. VENDA NOVA"

CONTAS = [
    {"cue_iid": "9001", "cue_ncuenta": "0002", "cue_cnombre": "SUPER NOSSO FLEMING FILIAL 420"},
    {"cue_iid": "9002", "cue_ncuenta": "0010", "cue_cnombre": "SUPER NOSSO CASTELO FILIAL 688"},
    {"cue_iid": "9003", "cue_ncuenta": "0011", "cue_cnombre": "APOIO (VENDA NOVA FILIAL 530)"},
    # A tesouraria é conta separada da loja e NUNCA é desligada.
    {"cue_iid": "9006", "cue_ncuenta": "0327", "cue_cnombre": "SUPER NOSSO CASTELO TESOURARIA"},
    # Base e Villefort entram na lista do portal, mas NÃO são elegíveis.
    {"cue_iid": "9004", "cue_ncuenta": "0420", "cue_cnombre": "PADARIA DO ZE 420"},
    {"cue_iid": "9005", "cue_ncuenta": "0030", "cue_cnombre": "VILLEFORT TROPICAL 688"},
]

TOLERANCIA_BASE = {
    "Id": 0, "Name": "", "tol_nnyo": 2, "tol_nnyc": 2, "tol_nControl": 2,
    "tol_dVacacionesDesde": "/Date(-2208988800000)/",
}


class FakePortal:
    """Guarda o estado como a plataforma guardaria: o PUT muda o valor, e
    a leitura seguinte vê o valor mudado."""

    def __init__(self, contas=None, *, nnyc=None, erro_em=None, erro_contas=None):
        self.contas = CONTAS if contas is None else contas
        # `tol_nnyc` de cada conta. 1 = gera o aviso (o normal), 2 = não
        # gera. A mesma régua do `tol_nnyo`, confirmada na tela da
        # plataforma.
        self.nnyc = nnyc or {c["cue_iid"]: 1 for c in self.contas}
        self.erro_em = erro_em or set()
        self.erro_contas = erro_contas
        self.puts = []

    def listar_todas_contas(self, **kwargs):
        if self.erro_contas:
            raise self.erro_contas
        return self.contas

    def ler_tolerancia(self, cue_iid):
        return {**TOLERANCIA_BASE, "Id": int(cue_iid), "tol_nnyc": self.nnyc[str(cue_iid)]}

    def set_nao_armado(self, cue_iid, *, gerar, original=None):
        chave = str(cue_iid)
        if chave in self.erro_em:
            raise SoftGuardError("a plataforma recusou")
        if gerar and original is None:
            raise SoftGuardError("religar exige o valor original")
        self.nnyc[chave] = int(original) if gerar else 2
        self.puts.append({"cue_iid": chave, "gerar": gerar, "nnyc": self.nnyc[chave]})
        return {"success": True}


def _desligada(cue_iid, conta="0002", nome="SUPER NOSSO X", nnyc=1):
    linha = AvisoArmeDesligado(
        cue_iid=cue_iid, conta=conta, nome=nome, nnyc_original=nnyc, ativo=True
    )
    db.session.add(linha)
    db.session.commit()
    return linha


# ---------- preparar: NÃO escreve ----------


def test_preparar_nao_escreve_nada(app):
    portal = FakePortal()

    svc.preparar(MENSAGEM, config=app.config, softguard_client=portal)

    assert portal.puts == []


def test_preparar_separa_desligar_de_religar(app):
    """Os dois sentidos do ciclo semanal."""
    _desligada("9003", conta="0011", nome="APOIO VENDA NOVA")
    _desligada("9099", conta="0099", nome="SUPER NOSSO QUE SAIU DA LISTA")

    preview = svc.preparar("420\n530", config=app.config, softguard_client=FakePortal())

    assert [c.cue_iid for c in preview["desligar"]] == ["9001"]
    assert [linha.cue_iid for linha in preview["religar"]] == ["9099"]
    assert [c.cue_iid for c in preview["ja_desligadas"]] == ["9003"]


def test_so_super_nosso_e_apoio_sao_elegiveis(app):
    """Um número de filial solto casaria com qualquer conta da base que
    tivesse esse número no nome."""
    preview = svc.preparar("420", config=app.config, softguard_client=FakePortal())

    assert [c.nome for c in preview["desligar"]] == ["SUPER NOSSO FLEMING FILIAL 420"]


def test_filial_desconhecida_fica_visivel(app):
    preview = svc.preparar("420\n777", config=app.config, softguard_client=FakePortal())

    assert [c.filial for c in preview["nao_encontrados"]] == ["777"]


def test_mensagem_sem_numero_avisa(app):
    with pytest.raises(svc.AvisoArmeError, match="número de filial"):
        svc.preparar("bom dia", config=app.config, softguard_client=FakePortal())


def test_portal_fora_do_ar_aborta_com_erro_proprio(app):
    portal = FakePortal(erro_contas=SoftGuardError("portal fora"))

    with pytest.raises(svc.AvisoArmeError, match="portal fora"):
        svc.preparar(MENSAGEM, config=app.config, softguard_client=portal)


# ---------- desligar ----------


def test_desligar_grava_nnyc_2_e_guarda_o_original(app, admin_user):
    portal = FakePortal(nnyc={"9001": 3, "9002": 1, "9003": 1, "9004": 1, "9005": 1, "9006": 1})

    svc.aplicar(["9001"], [], config=app.config, user=admin_user, softguard_client=portal)
    db.session.commit()

    assert portal.nnyc["9001"] == 2
    linha = AvisoArmeDesligado.query.filter_by(cue_iid="9001").one()
    assert linha.nnyc_original == 3  # o valor que a conta TINHA, não um chute
    assert linha.ativo is True


def test_o_ledger_e_gravado_antes_do_put(app, admin_user):
    """Se o processo morrer no meio, sobra uma linha dizendo "esta conta
    deveria estar desligada" — que se confere — em vez de uma conta
    desligada que ninguém sabe que existe."""
    portal = FakePortal(erro_em={"9001"})

    resultado = svc.aplicar(
        ["9001"], [], config=app.config, user=admin_user, softguard_client=portal
    )
    db.session.commit()

    # O PUT falhou: a conta continua ligada, então a linha some — o
    # inverso (ledger sem conta desligada) é inofensivo.
    assert AvisoArmeDesligado.query.count() == 0
    assert resultado["falhas"][0]["cue_iid"] == "9001"


def test_conta_ja_desligada_nao_e_regravada(app, admin_user):
    """Regravar trocaria o `nnyc_original` por 1, e aí o religar não
    teria mais o que restaurar. É o erro mais caro possível aqui."""
    _desligada("9001", nnyc=1)
    portal = FakePortal(nnyc={c["cue_iid"]: 2 for c in CONTAS})

    svc.aplicar(["9001"], [], config=app.config, user=admin_user, softguard_client=portal)
    db.session.commit()

    assert portal.puts == []
    assert AvisoArmeDesligado.query.filter_by(cue_iid="9001").one().nnyc_original == 1


# ---------- religar ----------


def test_religar_restaura_o_valor_do_ledger(app, admin_user):
    _desligada("9001", nnyc=3)
    portal = FakePortal(nnyc={c["cue_iid"]: 2 for c in CONTAS})

    svc.aplicar([], ["9001"], config=app.config, user=admin_user, softguard_client=portal)
    db.session.commit()

    assert portal.nnyc["9001"] == 3
    linha = AvisoArmeDesligado.query.filter_by(cue_iid="9001").one()
    assert linha.ativo is False
    assert linha.religado_em is not None


def test_ciclo_completo_desliga_novas_e_religa_as_que_sairam(app, admin_user):
    """O ciclo semanal inteiro: é ele que substitui a janela que expirava
    sozinha."""
    _desligada("9003", conta="0011", nome="APOIO VENDA NOVA", nnyc=1)
    portal = FakePortal(nnyc={"9001": 1, "9002": 1, "9003": 2, "9004": 1, "9005": 1, "9006": 1})

    resultado = svc.aplicar(
        ["9001"], ["9003"], config=app.config, user=admin_user, softguard_client=portal
    )
    db.session.commit()

    assert portal.nnyc["9001"] == 2  # desligada (2 = não gera)
    assert portal.nnyc["9003"] == 1  # religada no valor original
    assert resultado["desligadas"] == ["9001"]
    assert resultado["religadas"] == ["9003"]


def test_religar_conta_que_nao_consta_e_falha_registrada(app, admin_user):
    portal = FakePortal()

    resultado = svc.aplicar(
        [], ["9999"], config=app.config, user=admin_user, softguard_client=portal
    )
    db.session.commit()

    assert portal.puts == []
    assert "não consta" in resultado["falhas"][0]["erro"]


# ---------- tesouraria e resiliência ----------


def test_tesouraria_fica_fora_dos_elegiveis(app):
    elegiveis, barradas = svc.contas_do_super_nosso(CONTAS)

    assert [c.numero for c in barradas] == ["0327"]
    assert "0327" not in [c.numero for c in elegiveis]


def test_tesouraria_e_barrada_tambem_na_hora_de_gravar(app, admin_user):
    portal = FakePortal()

    resultado = svc.aplicar(
        ["9001", "9006"], [], config=app.config, user=admin_user, softguard_client=portal
    )
    db.session.commit()

    assert [p["cue_iid"] for p in portal.puts] == ["9001"]
    assert resultado["bloqueadas"] == ["9006"]


def test_falha_numa_conta_nao_derruba_as_outras(app, admin_user):
    portal = FakePortal(erro_em={"9002"})

    resultado = svc.aplicar(
        ["9001", "9002", "9003"], [], config=app.config, user=admin_user,
        softguard_client=portal,
    )
    db.session.commit()

    assert resultado["desligadas"] == ["9001", "9003"]
    assert resultado["falhas"][0]["cue_iid"] == "9002"


def test_lote_vazio_e_recusado(app, admin_user):
    with pytest.raises(svc.AvisoArmeError, match="Nenhuma conta"):
        svc.aplicar([], [], config=app.config, user=admin_user, softguard_client=FakePortal())


def test_lote_e_auditado_so_com_contagens(app, admin_user):
    from app.models.audit import AuditLog

    _desligada("9003", conta="0011", nome="APOIO VENDA NOVA")
    portal = FakePortal(erro_em={"9002"})

    svc.aplicar(
        ["9001", "9002"], ["9003"], config=app.config, user=admin_user,
        softguard_client=portal,
    )
    db.session.commit()

    entrada = AuditLog.query.filter_by(action="aviso_arme_lote").one()
    assert entrada.result == "failure"
    assert entrada.details["desligadas"] == 1
    assert entrada.details["religadas"] == 1
    assert entrada.details["falhas"] == 1
    assert "SUPER NOSSO" not in str(entrada.details)


def test_dias_desligado_conta_do_momento_do_desligamento(app):
    """Sem janela que expira sozinha, este contador é o único sintoma de
    que a lista parou de ser rodada."""
    from datetime import datetime, timedelta, timezone

    linha = _desligada("9001")
    linha.desligado_em = datetime.now(timezone.utc) - timedelta(days=23)
    db.session.commit()

    assert linha.dias_desligado() == 23


def test_escrita_que_nao_pega_nao_entra_no_ledger(app, admin_user):
    """Foi o que aconteceu em produção: a plataforma respondeu 200, o
    valor continuou o mesmo, e nove contas entraram no ledger como
    desligadas sem nada ter mudado. Registro falso de que a loja está
    coberta é pior que erro."""

    class PortalQueNaoAplica(FakePortal):
        def set_nao_armado(self, cue_iid, *, gerar, original=None):
            raise SoftGuardError("a tolerância da conta não mudou")

    portal = PortalQueNaoAplica()

    resultado = svc.aplicar(
        ["9001"], [], config=app.config, user=admin_user, softguard_client=portal
    )
    db.session.commit()

    assert AvisoArmeDesligado.query.count() == 0
    assert "não mudou" in resultado["falhas"][0]["erro"]
