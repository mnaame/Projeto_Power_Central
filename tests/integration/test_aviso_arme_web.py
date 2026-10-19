"""Tela de lojas sem arme — quem PODE apertar o botão, e o que é gravado."""

from app.extensions import db
from app.services import aviso_arme_service as svc
from tests.integration.test_aviso_arme_service import (
    CONTAS,
    MENSAGEM,
    FakePortal,
    _desligada,
)


def _preparar(monkeypatch, portal=None):
    alvo = portal or FakePortal()
    monkeypatch.setattr(svc, "_criar_cliente", lambda config: alvo)
    return alvo


# ---------- quem pode ----------


def test_index_exige_login(client):
    assert client.get("/aviso-arme").status_code == 302


def test_operador_nao_entra(operador_client):
    """Mexer na supervisão de arme não é operação de rotina."""
    assert operador_client.get("/aviso-arme").status_code == 403


def test_operador_nao_aplica(operador_client):
    assert operador_client.post("/aviso-arme/aplicar", data={}).status_code == 403


def test_admin_entra(admin_client):
    corpo = admin_client.get("/aviso-arme").get_data(as_text=True)

    assert "Lojas sem Arme" in corpo


def test_a_tela_diz_que_o_disparo_continua(admin_client):
    """É a diferença crucial para o mecanismo de "conta em teste", que
    calava tudo e por isso foi descartado."""
    corpo = admin_client.get("/aviso-arme").get_data(as_text=True)

    assert "disparo continua ativo" in corpo.lower()


def test_a_tela_avisa_que_nada_expira_sozinho(admin_client):
    corpo = admin_client.get("/aviso-arme").get_data(as_text=True)

    assert "expira sozinho" in corpo.lower()


# ---------- preparar ----------


def test_preparar_mostra_os_dois_sentidos_sem_gravar(admin_client, monkeypatch):
    _desligada("9099", conta="0099", nome="SUPER NOSSO QUE SAIU")
    portal = _preparar(monkeypatch)

    corpo = admin_client.post(
        "/aviso-arme/preparar", data={"mensagem": "420"}, follow_redirects=True
    ).get_data(as_text=True)

    assert "SUPER NOSSO FLEMING FILIAL 420" in corpo
    assert "SUPER NOSSO QUE SAIU" in corpo
    assert portal.puts == []


def test_preparar_mostra_a_tesouraria_barrada(admin_client, monkeypatch):
    _preparar(monkeypatch)

    corpo = admin_client.post(
        "/aviso-arme/preparar", data={"mensagem": "420"}, follow_redirects=True
    ).get_data(as_text=True)

    assert "Nunca são desligadas" in corpo
    assert "TESOURARIA" in corpo


# ---------- aplicar ----------


def test_sem_a_palavra_de_confirmacao_nao_grava(admin_client, monkeypatch):
    portal = _preparar(monkeypatch)
    admin_client.post("/aviso-arme/preparar", data={"mensagem": MENSAGEM})

    admin_client.post(
        "/aviso-arme/aplicar", data={"desligar": ["9001"]}, follow_redirects=True
    )

    assert portal.puts == []


def test_com_a_confirmacao_grava(admin_client, monkeypatch):
    portal = _preparar(monkeypatch)
    admin_client.post("/aviso-arme/preparar", data={"mensagem": MENSAGEM})

    corpo = admin_client.post(
        "/aviso-arme/aplicar",
        data={"desligar": ["9001"], "confirmacao": "DESLIGAR AVISO"},
        follow_redirects=True,
    ).get_data(as_text=True)

    assert portal.nnyc["9001"] == 1
    assert "disparo continua ativo" in corpo.lower()


def test_conta_fora_da_previsualizacao_e_ignorada(admin_client, monkeypatch):
    """A sessão é a autorização; o formulário é só o recorte dela."""
    portal = _preparar(monkeypatch)
    admin_client.post("/aviso-arme/preparar", data={"mensagem": "420"})

    admin_client.post(
        "/aviso-arme/aplicar",
        data={"desligar": ["9002"], "confirmacao": "DESLIGAR AVISO"},
        follow_redirects=True,
    )

    assert portal.puts == []


def test_aplicar_sem_preparar_antes_nao_grava(admin_client, monkeypatch):
    portal = _preparar(monkeypatch)

    corpo = admin_client.post(
        "/aviso-arme/aplicar",
        data={"desligar": ["9001"], "confirmacao": "DESLIGAR AVISO"},
        follow_redirects=True,
    ).get_data(as_text=True)

    assert portal.puts == []
    assert "Prepare a lista antes" in corpo


# ---------- as desligadas ficam à vista ----------


def test_tela_lista_o_que_esta_desligado_agora(admin_client):
    """Sem janela que expira sozinha, esta lista é o que impede uma conta
    de ser esquecida."""
    _desligada("9001", conta="0002", nome="SUPER NOSSO FLEMING")

    corpo = admin_client.get("/aviso-arme").get_data(as_text=True)

    assert "Desligadas agora" in corpo
    assert "SUPER NOSSO FLEMING" in corpo


def test_conta_desligada_ha_muito_tempo_e_destacada(admin_client):
    from datetime import datetime, timedelta, timezone

    linha = _desligada("9001", conta="0002", nome="ESQUECIDA")
    linha.desligado_em = datetime.now(timezone.utc) - timedelta(days=30)
    db.session.commit()

    corpo = admin_client.get("/aviso-arme").get_data(as_text=True)

    assert "30 dia(s)" in corpo
    assert "is-critical" in corpo


def test_religar_tudo_e_a_saida_de_emergencia(admin_client, monkeypatch):
    """Como nada expira sozinho, tem que existir um jeito de voltar ao
    normal que não dependa de o Super Nosso mandar a lista."""
    _desligada("9001", conta="0002", nome="SUPER NOSSO FLEMING", nnyc=2)
    portal = _preparar(monkeypatch, FakePortal(nnyc={c["cue_iid"]: 1 for c in CONTAS}))

    admin_client.post(
        "/aviso-arme/religar-tudo",
        data={"confirmacao": "DESLIGAR AVISO"},
        follow_redirects=True,
    )

    assert portal.nnyc["9001"] == 2


def test_religar_tudo_tambem_pede_confirmacao(admin_client, monkeypatch):
    _desligada("9001")
    portal = _preparar(monkeypatch)

    admin_client.post("/aviso-arme/religar-tudo", data={}, follow_redirects=True)

    assert portal.puts == []
