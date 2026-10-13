"""Rotas — junção PowerCentral + Auvo + de-para.

O risco deste módulo não é escrever errado (ele não escreve), é **ligar o
cliente à coordenada errada** e mandar o técnico para o endereço de outra
pessoa.
"""

from app.extensions import db
from app.integrations.softguard_client import SoftGuardError
from app.models.auvo import AuvoDepara
from app.services import rotas_service as svc

PRACA_SETE = (-19.9191, -43.9386)
VIZINHO = (-19.9195, -43.9380)
LONGE = (-19.9320, -44.0540)


def _conta(numero, nome, *, cidade="BELO HORIZONTE", localizacao=None):
    linha = {
        "cue_iid": f"9{numero}",
        "cue_ncuenta": numero,
        "cue_cnombre": nome,
        "city": cidade,
    }
    if localizacao is not None:
        linha["cue_clocalizacion"] = localizacao
    return linha


def _cliente_auvo(id_auvo, nome, coord=None):
    cliente = {"id": id_auvo, "description": nome}
    if coord:
        cliente["latitude"], cliente["longitude"] = coord
    return cliente


class FakeSoftGuard:
    def __init__(self, contas=None):
        self.contas = contas if contas is not None else []

    def listar_todas_contas(self, **kwargs):
        if isinstance(self.contas, Exception):
            raise self.contas
        return self.contas


class FakeAuvo:
    def __init__(self, clientes=None, *, erro=None):
        self.clientes = clientes or []
        self.erro = erro

    def listar_clientes(self):
        if self.erro:
            raise self.erro
        return self.clientes


def _montar(app, monkeypatch, *, contas, clientes_auvo=None, erro_auvo=None, raio=1.5):
    monkeypatch.setattr(
        svc, "SoftGuardClient", lambda *a, **k: FakeSoftGuard(contas)
    )
    monkeypatch.setattr(svc, "credenciais_softguard", lambda config: None)
    monkeypatch.setattr(
        svc.auvo_service, "criar_cliente",
        lambda config: FakeAuvo(clientes_auvo, erro=erro_auvo),
    )
    return svc.montar_rotas(config=app.config, raio_km=raio)


# ---------- quem é base ----------


def test_villefort_super_nosso_e_apoio_ficam_de_fora(app, monkeypatch):
    """A classificação é a de `disparos_geral` — ter duas definições de
    "quem é Villefort" seria o começo de dois números diferentes."""
    contas = [
        _conta("1", "VILLEFORT TROPICAL"),
        _conta("2", "SUPER NOSSO CASTELO"),
        _conta("3", "APOIO VESPASIANO"),
        _conta("4", "PADARIA DO ZE"),
    ]

    resultado = _montar(app, monkeypatch, contas=contas)

    assert resultado["resumo"]["base"] == 1
    assert [s["nome"] for s in resultado["sem_coord"]] == ["PADARIA DO ZE"]


def test_contas_internas_ficam_de_fora(app, monkeypatch):
    contas = [
        _conta("1", "NOVO MILLENIUM"),
        _conta("2", "CONTA TESTE ITALO"),
        _conta("3", "PADARIA DO ZE"),
    ]

    assert _montar(app, monkeypatch, contas=contas)["resumo"]["base"] == 1


# ---------- de onde vem a coordenada ----------


def test_coordenada_vem_da_auvo_pelo_depara(app, monkeypatch):
    db.session.add(AuvoDepara(conta_power="95", id_auvo=500, status="OK", nome_power="PADARIA"))
    db.session.commit()
    contas = [_conta("0095", "PADARIA DO ZE")]
    clientes = [_cliente_auvo(500, "NOME TOTALMENTE DIFERENTE", PRACA_SETE)]

    resultado = _montar(app, monkeypatch, contas=contas, clientes_auvo=clientes)

    assert resultado["resumo"]["de_auvo"] == 1
    assert resultado["rotas"][0].pontos[0].lat == PRACA_SETE[0]


def test_depara_em_revisar_nao_e_usado(app, monkeypatch):
    """REVISAR é casamento não confirmado por humano — usá-lo mandaria o
    técnico para o endereço de outro cliente."""
    db.session.add(AuvoDepara(conta_power="95", id_auvo=500, status="REVISAR", nome_power="X"))
    db.session.commit()
    contas = [_conta("0095", "PADARIA DO ZE")]
    clientes = [_cliente_auvo(500, "OUTRO NOME QUALQUER", PRACA_SETE)]

    resultado = _montar(app, monkeypatch, contas=contas, clientes_auvo=clientes)

    assert resultado["resumo"]["com_coord"] == 0


def test_sem_depara_casa_por_nome(app, monkeypatch):
    contas = [_conta("0095", "PADARIA DO ZE")]
    clientes = [_cliente_auvo(500, "Padaria do Zé", PRACA_SETE)]

    resultado = _montar(app, monkeypatch, contas=contas, clientes_auvo=clientes)

    assert resultado["resumo"]["de_auvo"] == 1


def test_nome_que_nao_casa_nao_inventa_coordenada(app, monkeypatch):
    contas = [_conta("0095", "PADARIA DO ZE")]
    clientes = [_cliente_auvo(500, "ACADEMIA CORPO E MENTE", PRACA_SETE)]

    resultado = _montar(app, monkeypatch, contas=contas, clientes_auvo=clientes)

    assert resultado["resumo"]["com_coord"] == 0
    assert resultado["sem_coord"][0]["conta"] == "0095"


def test_localizacao_da_power_e_a_reserva(app, monkeypatch):
    contas = [_conta("0095", "PADARIA DO ZE", localizacao="-19.9191,-43.9386")]

    resultado = _montar(app, monkeypatch, contas=contas, clientes_auvo=[])

    assert resultado["resumo"]["da_power"] == 1
    assert resultado["rotas"][0].pontos[0].fonte == "PowerCentral"


def test_auvo_tem_prioridade_sobre_a_power(app, monkeypatch):
    """A Auvo é o app de campo: a coordenada dela foi conferida por quem
    esteve no local."""
    contas = [_conta("0095", "PADARIA DO ZE", localizacao="-19.9320,-44.0540")]
    clientes = [_cliente_auvo(500, "PADARIA DO ZE", PRACA_SETE)]

    resultado = _montar(app, monkeypatch, contas=contas, clientes_auvo=clientes)

    assert resultado["rotas"][0].pontos[0].fonte == "Auvo"
    assert resultado["rotas"][0].pontos[0].lat == PRACA_SETE[0]


def test_localizacao_da_power_fora_da_regiao_e_descartada(app, monkeypatch):
    """Parte das coordenadas da Power aponta para outro estado — e uma
    coordenada errada distorce o centroide da rota inteira."""
    contas = [_conta("0095", "PADARIA DO ZE", localizacao="-23.5505,-46.6333")]

    resultado = _montar(app, monkeypatch, contas=contas, clientes_auvo=[])

    assert resultado["resumo"]["com_coord"] == 0
    assert len(resultado["sem_coord"]) == 1


# ---------- agrupamento ponta a ponta ----------


def test_clientes_proximos_entram_na_mesma_rota(app, monkeypatch):
    contas = [_conta("1", "A"), _conta("2", "B"), _conta("3", "C")]
    clientes = [
        _cliente_auvo(1, "A", PRACA_SETE),
        _cliente_auvo(2, "B", VIZINHO),
        _cliente_auvo(3, "C", LONGE),
    ]

    resultado = _montar(app, monkeypatch, contas=contas, clientes_auvo=clientes)

    assert resultado["resumo"]["clusters"] == 2
    assert resultado["rotas"][0].tamanho == 2


def test_raio_maior_junta_tudo(app, monkeypatch):
    contas = [_conta("1", "A"), _conta("2", "C")]
    clientes = [_cliente_auvo(1, "A", PRACA_SETE), _cliente_auvo(2, "C", LONGE)]

    resultado = _montar(app, monkeypatch, contas=contas, clientes_auvo=clientes, raio=20)

    assert resultado["resumo"]["clusters"] == 1


# ---------- resiliência ----------


def test_auvo_fora_do_ar_nao_cancela_tudo(app, monkeypatch):
    """Sem a Auvo sobra a coordenada da Power: entregar metade é melhor
    que entregar nada — e o resumo diz que faltou."""
    contas = [_conta("0095", "PADARIA", localizacao="-19.9191,-43.9386")]

    resultado = _montar(
        app, monkeypatch, contas=contas, erro_auvo=RuntimeError("Auvo fora")
    )

    assert resultado["resumo"]["com_coord"] == 1
    assert "Auvo fora" in resultado["resumo"]["erro_auvo"]


def test_auvo_nao_configurada_e_avisada_sem_derrubar(app, monkeypatch):
    contas = [_conta("0095", "PADARIA", localizacao="-19.9191,-43.9386")]
    monkeypatch.setattr(
        svc, "SoftGuardClient", lambda *a, **k: FakeSoftGuard(contas)
    )
    monkeypatch.setattr(svc, "credenciais_softguard", lambda config: None)
    monkeypatch.setattr(svc.auvo_service, "criar_cliente", lambda config: None)

    resultado = svc.montar_rotas(config=app.config, raio_km=1.5)

    assert resultado["resumo"]["com_coord"] == 1
    assert "não configurada" in resultado["resumo"]["erro_auvo"]


def test_power_fora_do_ar_aborta_com_erro_proprio(app, monkeypatch):
    monkeypatch.setattr(
        svc, "SoftGuardClient", lambda *a, **k: FakeSoftGuard(SoftGuardError("portal fora"))
    )
    monkeypatch.setattr(svc, "credenciais_softguard", lambda config: None)
    monkeypatch.setattr(svc.auvo_service, "criar_cliente", lambda config: FakeAuvo([]))

    try:
        svc.montar_rotas(config=app.config, raio_km=1.5)
    except svc.RotasError as exc:
        assert "portal fora" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("deveria ter levantado RotasError")


def test_geracao_e_auditada_so_com_contadores(app, monkeypatch, admin_user):
    from app.models.audit import AuditLog

    contas = [_conta("0095", "PADARIA SIGILOSA", localizacao="-19.9191,-43.9386")]
    monkeypatch.setattr(svc, "SoftGuardClient", lambda *a, **k: FakeSoftGuard(contas))
    monkeypatch.setattr(svc, "credenciais_softguard", lambda config: None)
    monkeypatch.setattr(svc.auvo_service, "criar_cliente", lambda config: FakeAuvo([]))

    svc.montar_rotas(config=app.config, raio_km=1.5, user=admin_user)
    db.session.commit()

    entrada = AuditLog.query.filter_by(action="rotas_geradas").one()
    assert len(entrada.action) <= 48
    assert entrada.details == {"base": 1, "com_coord": 1, "clusters": 1, "raio_km": 1.5}
    assert "PADARIA SIGILOSA" not in str(entrada.details)
