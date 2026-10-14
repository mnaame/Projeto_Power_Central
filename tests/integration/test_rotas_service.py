"""Catálogo por bairro — junção PowerCentral + Auvo + planilhas.

O risco deste módulo não é escrever errado (ele não escreve), é **colocar
o cliente no bairro de outro** e mandar o técnico para a região errada.
"""

import io
import zipfile

import pytest

from app.extensions import db
from app.integrations.softguard_client import SoftGuardError
from app.models.auvo import AuvoDepara
from app.models.rotas import RotasCiclo, RotasEndereco
from app.services import rotas_service as svc

ENDERECO_SAVASSI = "Rua Antônio de Albuquerque, 100,,Savassi,Belo Horizonte,MG,30112010"
ENDERECO_BURITIS = "Rua Engenheiro Zoroastro, 50,,Buritis,Belo Horizonte,MG,30575100"

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _conta(numero, nome, *, cidade=None, endereco=None):
    linha = {
        "cue_iid": f"9{numero}",
        "cue_ncuenta": numero,
        "cue_cnombre": nome,
    }
    if cidade is not None:
        # Nome de campo deliberadamente improvável: chutar nome de campo
        # já custou uma rodada inteira deste módulo (105 contas, zero
        # resultado, nenhum erro na tela).
        linha["campo_cujo_nome_eu_nao_sei"] = cidade
    if endereco is not None:
        linha["outro_campo_qualquer"] = endereco
    return linha


def _cliente_auvo(id_auvo, nome, endereco=None):
    cliente = {"id": id_auvo, "description": nome}
    if endereco:
        cliente["address"] = endereco
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


def _montar(app, monkeypatch, *, contas, clientes_auvo=None, erro_auvo=None):
    monkeypatch.setattr(svc, "SoftGuardClient", lambda *a, **k: FakeSoftGuard(contas))
    monkeypatch.setattr(svc, "credenciais_softguard", lambda config: None)
    monkeypatch.setattr(
        svc.auvo_service,
        "criar_cliente",
        lambda config: FakeAuvo(clientes_auvo, erro=erro_auvo),
    )
    # `montar_catalogo` devolve o CICLO gravado; `catalogo()` é o que a
    # tela monta a partir dele. Os testes olham o segundo.
    return svc.catalogo(svc.montar_catalogo(config=app.config))


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


def test_contas_internas_ficam_de_fora(app, monkeypatch):
    contas = [
        _conta("1", "NOVO MILLENIUM"),
        _conta("2", "CONTA TESTE ITALO"),
        _conta("3", "PADARIA DO ZE"),
    ]

    assert _montar(app, monkeypatch, contas=contas)["resumo"]["base"] == 1


# ---------- de onde vem o bairro ----------


def test_bairro_vem_da_auvo_pelo_depara(app, monkeypatch):
    db.session.add(
        AuvoDepara(conta_power="95", id_auvo=500, status="OK", nome_power="PADARIA")
    )
    db.session.commit()
    contas = [_conta("0095", "PADARIA DO ZE")]
    clientes = [_cliente_auvo(500, "NOME TOTALMENTE DIFERENTE", ENDERECO_SAVASSI)]

    resultado = _montar(app, monkeypatch, contas=contas, clientes_auvo=clientes)

    assert resultado["regioes"][0].rotulo == "Savassi — Belo Horizonte"


def test_depara_em_revisar_nao_e_usado(app, monkeypatch):
    """REVISAR é casamento não confirmado por humano — usá-lo colocaria o
    cliente no bairro de outro."""
    db.session.add(
        AuvoDepara(conta_power="95", id_auvo=500, status="REVISAR", nome_power="X")
    )
    db.session.commit()
    contas = [_conta("0095", "PADARIA DO ZE")]
    clientes = [_cliente_auvo(500, "OUTRO NOME QUALQUER", ENDERECO_SAVASSI)]

    resultado = _montar(app, monkeypatch, contas=contas, clientes_auvo=clientes)

    assert resultado["resumo"]["com_bairro"] == 0


def test_sem_depara_casa_por_nome(app, monkeypatch):
    contas = [_conta("0095", "PADARIA DO ZE")]
    clientes = [_cliente_auvo(500, "Padaria do Zé", ENDERECO_SAVASSI)]

    resultado = _montar(app, monkeypatch, contas=contas, clientes_auvo=clientes)

    assert resultado["resumo"]["com_bairro"] == 1


def test_nome_que_nao_casa_nao_inventa_bairro(app, monkeypatch):
    contas = [_conta("0095", "PADARIA DO ZE")]
    clientes = [_cliente_auvo(500, "ACADEMIA CORPO E MENTE", ENDERECO_SAVASSI)]

    resultado = _montar(app, monkeypatch, contas=contas, clientes_auvo=clientes)

    assert resultado["resumo"]["com_bairro"] == 0


def test_endereco_e_achado_mesmo_em_campo_de_nome_desconhecido(app, monkeypatch):
    """A aposta no nome do campo já falhou neste módulo. O endereço se
    prova sozinho: tem UF e CEP."""
    cliente = {"id": 500, "description": "PADARIA DO ZE", "campo_exotico": ENDERECO_SAVASSI}
    contas = [_conta("0095", "PADARIA DO ZE")]

    resultado = _montar(app, monkeypatch, contas=contas, clientes_auvo=[cliente])

    assert resultado["regioes"][0].rotulo == "Savassi — Belo Horizonte"


def test_texto_qualquer_nao_passa_por_endereco(app, monkeypatch):
    """Sem UF nem CEP não é endereço — é observação, nome, o que for."""
    cliente = {
        "id": 500,
        "description": "PADARIA DO ZE",
        "observacao": "cliente antigo, chave na portaria, falar com o Joao",
    }
    contas = [_conta("0095", "PADARIA DO ZE")]

    resultado = _montar(app, monkeypatch, contas=contas, clientes_auvo=[cliente])

    assert resultado["resumo"]["com_bairro"] == 0


# ---------- planilha importada ----------


def _xlsx_auvo(linhas):
    corpo = []
    for n, linha in enumerate(linhas, start=1):
        celulas = "".join(
            f'<c r="{chr(65 + i)}{n}" t="inlineStr"><is><t>{v}</t></is></c>'
            for i, v in enumerate(linha)
        )
        corpo.append(f'<row r="{n}">{celulas}</row>')
    sheet = (
        f'<?xml version="1.0"?><worksheet xmlns="{NS}"><sheetData>'
        + "".join(corpo)
        + "</sheetData></worksheet>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return buffer.getvalue()


def _html_power(linhas):
    corpo = "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in linha) + "</tr>" for linha in linhas
    )
    return f"<html><body><table>{corpo}</table></body></html>".encode("latin-1")


def test_planilha_da_auvo_da_o_bairro_quando_a_api_nao_da(app, monkeypatch):
    """É a razão de a importação existir: o catálogo não pode depender de
    a API expor o campo com o nome que a gente espera."""
    svc.importar_planilha(
        _xlsx_auvo(
            [
                ["Código", "Nome", "Endereço"],
                ["500", "PADARIA DO ZE", ENDERECO_SAVASSI],
            ]
        )
    )
    db.session.commit()
    contas = [_conta("0095", "PADARIA DO ZE")]

    resultado = _montar(app, monkeypatch, contas=contas, clientes_auvo=[])

    assert resultado["regioes"][0].rotulo == "Savassi — Belo Horizonte"
    assert resultado["regioes"][0].clientes[0].fonte == "Auvo (planilha)"


def test_planilha_da_power_da_a_cidade_de_quem_nao_casou_na_auvo(app, monkeypatch):
    """Das 148 contas do relatório real, a coluna "Rua" tinha bairro em
    uma — mas a cidade vinha em 147. Sem ela, quem não casa com a Auvo
    não teria nem região."""
    svc.importar_planilha(
        _html_power(
            [
                ["Dealer / Conta", "Nome", "Localidade"],
                ["MIL-0095", "PADARIA DO ZE", "CONTAGEM"],
            ]
        )
    )
    db.session.commit()
    contas = [_conta("0095", "PADARIA DO ZE")]

    resultado = _montar(app, monkeypatch, contas=contas, clientes_auvo=[])

    assert resultado["regioes"][0].rotulo == "(sem bairro) — Contagem"
    assert resultado["resumo"]["sem_regiao"] == 0


def test_api_tem_prioridade_sobre_a_planilha(app, monkeypatch):
    """A planilha é um retrato datado; a API é o cadastro de agora."""
    svc.importar_planilha(
        _xlsx_auvo(
            [["Código", "Nome", "Endereço"], ["500", "PADARIA DO ZE", ENDERECO_BURITIS]]
        )
    )
    db.session.commit()
    contas = [_conta("0095", "PADARIA DO ZE")]
    clientes = [_cliente_auvo(500, "PADARIA DO ZE", ENDERECO_SAVASSI)]

    resultado = _montar(app, monkeypatch, contas=contas, clientes_auvo=clientes)

    assert resultado["regioes"][0].rotulo == "Savassi — Belo Horizonte"
    assert resultado["regioes"][0].clientes[0].fonte == "Auvo"


def test_reimportar_substitui_a_fonte_inteira(app, monkeypatch):
    """A planilha é o retrato completo daquele lado. Misturar com o lote
    anterior deixaria no sistema o endereço de quem já mudou."""
    svc.importar_planilha(
        _xlsx_auvo(
            [
                ["Código", "Nome", "Endereço"],
                ["500", "PADARIA DO ZE", ENDERECO_SAVASSI],
                ["501", "CLIENTE QUE SAIU", ENDERECO_BURITIS],
            ]
        )
    )
    db.session.commit()

    svc.importar_planilha(
        _xlsx_auvo(
            [["Código", "Nome", "Endereço"], ["500", "PADARIA DO ZE", ENDERECO_BURITIS]]
        )
    )
    db.session.commit()

    linhas = RotasEndereco.query.filter_by(fonte="auvo").all()
    assert len(linhas) == 1
    assert linhas[0].bairro == "Buritis"


def test_importar_a_power_nao_apaga_a_auvo(app, monkeypatch):
    """Cada envio substitui só a sua própria origem."""
    svc.importar_planilha(
        _xlsx_auvo([["Código", "Nome", "Endereço"], ["500", "PADARIA", ENDERECO_SAVASSI]])
    )
    svc.importar_planilha(
        _html_power([["Dealer / Conta", "Nome", "Localidade"], ["MIL-0095", "P", "BH"]])
    )
    db.session.commit()

    assert RotasEndereco.query.filter_by(fonte="auvo").count() == 1
    assert RotasEndereco.query.filter_by(fonte="power").count() == 1


def test_importacao_guarda_o_endereco_bruto_para_conferencia(app):
    """Sem o original, "o bairro saiu errado" não tem como ser apurado."""
    svc.importar_planilha(
        _xlsx_auvo([["Código", "Nome", "Endereço"], ["500", "PADARIA", ENDERECO_SAVASSI]])
    )
    db.session.commit()

    assert RotasEndereco.query.one().endereco_bruto == ENDERECO_SAVASSI


def test_planilha_irreconhecivel_e_recusada_sem_apagar_o_que_havia(app):
    svc.importar_planilha(
        _xlsx_auvo([["Código", "Nome", "Endereço"], ["500", "PADARIA", ENDERECO_SAVASSI]])
    )
    db.session.commit()

    with pytest.raises(svc.dom_pl.PlanilhaInvalida):
        svc.importar_planilha(b"isto nao e planilha nenhuma")
    db.session.rollback()

    assert RotasEndereco.query.count() == 1


# ---------- resiliência ----------


def test_auvo_fora_do_ar_nao_cancela_tudo(app, monkeypatch):
    """Sem a Auvo sobram a planilha e a PowerCentral: entregar parte é
    melhor que não entregar nada — e o resumo diz que faltou."""
    contas = [_conta("0095", "PADARIA", cidade="BELO HORIZONTE")]

    resultado = _montar(
        app, monkeypatch, contas=contas, erro_auvo=RuntimeError("Auvo fora")
    )

    assert "Auvo fora" in resultado["resumo"]["erro_auvo"]
    assert resultado["resumo"]["base"] == 1


def test_auvo_nao_configurada_e_avisada_sem_derrubar(app, monkeypatch):
    monkeypatch.setattr(svc, "SoftGuardClient", lambda *a, **k: FakeSoftGuard([]))
    monkeypatch.setattr(svc, "credenciais_softguard", lambda config: None)
    monkeypatch.setattr(svc.auvo_service, "criar_cliente", lambda config: None)

    resultado = svc.catalogo(svc.montar_catalogo(config=app.config))

    assert "não configurada" in resultado["resumo"]["erro_auvo"]


def test_power_fora_do_ar_aborta_com_erro_proprio(app, monkeypatch):
    monkeypatch.setattr(
        svc, "SoftGuardClient", lambda *a, **k: FakeSoftGuard(SoftGuardError("portal fora"))
    )
    monkeypatch.setattr(svc, "credenciais_softguard", lambda config: None)
    monkeypatch.setattr(svc.auvo_service, "criar_cliente", lambda config: FakeAuvo([]))

    with pytest.raises(svc.RotasError, match="portal fora"):
        svc.montar_catalogo(config=app.config)


def test_geracao_e_auditada_so_com_contadores(app, monkeypatch, admin_user):
    from app.models.audit import AuditLog

    contas = [_conta("0095", "PADARIA SIGILOSA", cidade="BELO HORIZONTE")]
    monkeypatch.setattr(svc, "SoftGuardClient", lambda *a, **k: FakeSoftGuard(contas))
    monkeypatch.setattr(svc, "credenciais_softguard", lambda config: None)
    monkeypatch.setattr(svc.auvo_service, "criar_cliente", lambda config: FakeAuvo([]))

    svc.montar_catalogo(config=app.config, user=admin_user)
    db.session.commit()

    entrada = AuditLog.query.filter_by(action="rotas_catalogo_gerado").one()
    assert len(entrada.action) <= 48
    assert "PADARIA SIGILOSA" not in str(entrada.details)


# ---------- o ciclo de preventivas ----------


def test_gerar_duas_vezes_nao_cria_dois_ciclos(app, monkeypatch):
    """Gerar é rotina — se cada geração abrisse uma rodada, o número do
    ciclo viraria ruído e a progressão não significaria nada."""
    contas = [_conta("0095", "PADARIA DO ZE")]
    monkeypatch.setattr(svc, "SoftGuardClient", lambda *a, **k: FakeSoftGuard(contas))
    monkeypatch.setattr(svc, "credenciais_softguard", lambda config: None)
    monkeypatch.setattr(svc.auvo_service, "criar_cliente", lambda config: FakeAuvo([]))

    primeiro = svc.montar_catalogo(config=app.config)
    db.session.commit()
    segundo = svc.montar_catalogo(config=app.config)
    db.session.commit()

    assert primeiro.id == segundo.id
    assert RotasCiclo.query.count() == 1


def test_conta_que_sai_da_base_sai_do_ciclo(app, monkeypatch):
    contas = [_conta("0095", "PADARIA"), _conta("0096", "ACADEMIA")]
    monkeypatch.setattr(svc, "SoftGuardClient", lambda *a, **k: FakeSoftGuard(contas))
    monkeypatch.setattr(svc, "credenciais_softguard", lambda config: None)
    monkeypatch.setattr(svc.auvo_service, "criar_cliente", lambda config: FakeAuvo([]))
    svc.montar_catalogo(config=app.config)
    db.session.commit()

    contas.pop()  # a conta sumiu da PowerCentral
    ciclo = svc.montar_catalogo(config=app.config)
    db.session.commit()

    assert [linha.conta for linha in ciclo.clientes] == ["0095"]


def test_visita_de_conta_que_continua_no_catalogo_e_preservada(app, monkeypatch):
    contas = [_conta("0095", "PADARIA"), _conta("0096", "ACADEMIA")]
    monkeypatch.setattr(svc, "SoftGuardClient", lambda *a, **k: FakeSoftGuard(contas))
    monkeypatch.setattr(svc, "credenciais_softguard", lambda config: None)
    monkeypatch.setattr(svc.auvo_service, "criar_cliente", lambda config: FakeAuvo([]))
    ciclo = svc.montar_catalogo(config=app.config)
    svc.marcar_visita(ciclo, "0095", visitado=True)
    db.session.commit()

    ciclo = svc.montar_catalogo(config=app.config)
    db.session.commit()

    assert svc.catalogo(ciclo)["visitados"] == 1


def test_reiniciar_encerra_o_ciclo_e_abre_o_seguinte(app, monkeypatch):
    contas = [_conta("0095", "PADARIA")]
    monkeypatch.setattr(svc, "SoftGuardClient", lambda *a, **k: FakeSoftGuard(contas))
    monkeypatch.setattr(svc, "credenciais_softguard", lambda config: None)
    monkeypatch.setattr(svc.auvo_service, "criar_cliente", lambda config: FakeAuvo([]))
    ciclo = svc.montar_catalogo(config=app.config)
    svc.marcar_visita(ciclo, "0095", visitado=True)
    db.session.commit()

    novo = svc.reiniciar_ciclo(ciclo)
    db.session.commit()

    assert ciclo.encerrado_em is not None
    assert novo.numero == ciclo.numero + 1
    assert svc.catalogo(novo)["visitados"] == 0
    assert svc.catalogo(novo)["total"] == 1
    assert svc.ciclo_atual().id == novo.id


def test_o_ciclo_encerrado_guarda_o_que_foi_visitado(app, monkeypatch):
    """A rodada anterior é o histórico das preventivas — zerar por cima
    dela apagaria quando cada local foi atendido."""
    contas = [_conta("0095", "PADARIA")]
    monkeypatch.setattr(svc, "SoftGuardClient", lambda *a, **k: FakeSoftGuard(contas))
    monkeypatch.setattr(svc, "credenciais_softguard", lambda config: None)
    monkeypatch.setattr(svc.auvo_service, "criar_cliente", lambda config: FakeAuvo([]))
    ciclo = svc.montar_catalogo(config=app.config)
    svc.marcar_visita(ciclo, "0095", visitado=True)
    db.session.commit()

    svc.reiniciar_ciclo(ciclo)
    db.session.commit()

    antigo = RotasCiclo.query.filter(RotasCiclo.encerrado_em.isnot(None)).one()
    assert antigo.clientes.first().visitado_em is not None


def test_marcar_conta_de_fora_do_ciclo_e_recusado(app, monkeypatch):
    contas = [_conta("0095", "PADARIA")]
    monkeypatch.setattr(svc, "SoftGuardClient", lambda *a, **k: FakeSoftGuard(contas))
    monkeypatch.setattr(svc, "credenciais_softguard", lambda config: None)
    monkeypatch.setattr(svc.auvo_service, "criar_cliente", lambda config: FakeAuvo([]))
    ciclo = svc.montar_catalogo(config=app.config)
    db.session.commit()

    with pytest.raises(svc.RotasError, match="0999"):
        svc.marcar_visita(ciclo, "0999", visitado=True)


def test_marcar_visita_e_auditado_com_a_conta(app, monkeypatch, admin_user):
    from app.models.audit import AuditLog

    contas = [_conta("0095", "PADARIA")]
    monkeypatch.setattr(svc, "SoftGuardClient", lambda *a, **k: FakeSoftGuard(contas))
    monkeypatch.setattr(svc, "credenciais_softguard", lambda config: None)
    monkeypatch.setattr(svc.auvo_service, "criar_cliente", lambda config: FakeAuvo([]))
    ciclo = svc.montar_catalogo(config=app.config)

    svc.marcar_visita(ciclo, "0095", visitado=True, user=admin_user)
    db.session.commit()

    entrada = AuditLog.query.filter_by(action="rotas_visita_marcada").one()
    assert entrada.details["conta"] == "0095"
