from io import BytesIO

from openpyxl import load_workbook

from app.services import rotas_service as svc
from tests.integration.test_rotas_service import (
    LONGE,
    PRACA_SETE,
    VIZINHO,
    FakeAuvo,
    FakeSoftGuard,
    _cliente_auvo,
    _conta,
)

CONTAS = [_conta("1", "A"), _conta("2", "B"), _conta("3", "C"), _conta("4", "SEM COORD")]
CLIENTES = [
    _cliente_auvo(1, "A", PRACA_SETE),
    _cliente_auvo(2, "B", VIZINHO),
    _cliente_auvo(3, "C", LONGE),
]


def _preparar(monkeypatch, contas=None, clientes=None):
    monkeypatch.setattr(
        svc, "SoftGuardClient", lambda *a, **k: FakeSoftGuard(contas or CONTAS)
    )
    monkeypatch.setattr(svc, "credenciais_softguard", lambda config: None)
    monkeypatch.setattr(
        svc.auvo_service, "criar_cliente",
        lambda config: FakeAuvo(CLIENTES if clientes is None else clientes),
    )


def test_index_exige_login(client):
    resposta = client.get("/rotas")
    assert resposta.status_code == 302
    assert "/login" in resposta.headers["Location"]


def test_operador_pode_ver(operador_client):
    """Só leitura — não é tela de admin."""
    assert operador_client.get("/rotas").status_code == 200


def test_index_sem_rotas_convida_a_gerar(operador_client):
    assert "Nenhuma rota gerada ainda" in operador_client.get("/rotas").get_data(as_text=True)


def test_gerar_mostra_resumo_tabela_e_mapa(operador_client, monkeypatch):
    _preparar(monkeypatch)

    corpo = operador_client.post(
        "/rotas/gerar", data={"raio_km": "1.5"}, follow_redirects=True
    ).get_data(as_text=True)

    assert "Rota 1" in corpo
    assert "id=\"mapa-rotas\"" in corpo
    assert "vendor/leaflet/leaflet.js" in corpo  # vendorizado, não CDN
    assert "SEM COORD" in corpo  # o que ficou de fora aparece


def test_mapa_so_carrega_o_leaflet_quando_ha_rotas(operador_client):
    corpo = operador_client.get("/rotas").get_data(as_text=True)

    assert "leaflet.js" not in corpo


def test_raio_zero_e_recusado(operador_client, monkeypatch):
    _preparar(monkeypatch)

    corpo = operador_client.post(
        "/rotas/gerar", data={"raio_km": "0"}, follow_redirects=True
    ).get_data(as_text=True)

    assert "maior que zero" in corpo


def test_exportar_sem_gerar_avisa(operador_client):
    corpo = operador_client.get("/rotas/exportar", follow_redirects=True).get_data(as_text=True)

    assert "Gere as rotas antes" in corpo


def test_export_tem_as_tres_abas(operador_client, monkeypatch):
    _preparar(monkeypatch)
    operador_client.post("/rotas/gerar", data={"raio_km": "1.5"})

    resposta = operador_client.get("/rotas/exportar")

    assert resposta.status_code == 200
    wb = load_workbook(BytesIO(resposta.data))
    assert wb.sheetnames == ["Clientes por rota", "Resumo por rota", "Sem coordenada"]
    assert [c.value for c in wb["Clientes por rota"][1]][:4] == [
        "ROTA", "ORDEM", "CONTA", "CLIENTE"
    ]
    assert wb["Sem coordenada"].max_row == 2  # cabeçalho + o cliente sem coord


def test_export_traz_exatamente_o_que_esta_na_tela(operador_client, monkeypatch):
    """O resultado fica na sessão: exportar não refaz a consulta, que
    leva minutos e poderia dar outro número."""
    _preparar(monkeypatch)
    operador_client.post("/rotas/gerar", data={"raio_km": "1.5"})

    # A plataforma "muda" depois de gerar; o export não pode mudar junto.
    _preparar(monkeypatch, contas=[_conta("9", "OUTRA COISA")], clientes=[])
    wb = load_workbook(BytesIO(operador_client.get("/rotas/exportar").data))

    contas = {wb["Clientes por rota"].cell(row=l, column=3).value for l in range(2, 5)}
    assert "9" not in contas


def test_raio_negativo_tambem_e_recusado(operador_client, monkeypatch):
    _preparar(monkeypatch)

    corpo = operador_client.post(
        "/rotas/gerar", data={"raio_km": "-2"}, follow_redirects=True
    ).get_data(as_text=True)

    assert "maior que zero" in corpo


def test_sem_raio_informado_usa_o_padrao(operador_client, monkeypatch):
    _preparar(monkeypatch)

    corpo = operador_client.post("/rotas/gerar", data={}, follow_redirects=True).get_data(
        as_text=True
    )

    assert "Rota 1" in corpo
