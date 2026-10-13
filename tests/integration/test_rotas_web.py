from io import BytesIO

from openpyxl import load_workbook

from app.services import rotas_service as svc
from tests.integration.test_rotas_service import (
    ENDERECO_BURITIS,
    ENDERECO_SAVASSI,
    FakeAuvo,
    FakeSoftGuard,
    _cliente_auvo,
    _conta,
    _xlsx_auvo,
)

CONTAS = [
    _conta("1", "A"),
    _conta("2", "B"),
    _conta("3", "C"),
    _conta("4", "SEM BAIRRO", cidade="CONTAGEM"),
]
CLIENTES = [
    _cliente_auvo(1, "A", ENDERECO_SAVASSI),
    _cliente_auvo(2, "B", ENDERECO_SAVASSI),
    _cliente_auvo(3, "C", ENDERECO_BURITIS),
]


def _preparar(monkeypatch, contas=None, clientes=None):
    monkeypatch.setattr(
        svc, "SoftGuardClient", lambda *a, **k: FakeSoftGuard(contas or CONTAS)
    )
    monkeypatch.setattr(svc, "credenciais_softguard", lambda config: None)
    monkeypatch.setattr(
        svc.auvo_service,
        "criar_cliente",
        lambda config: FakeAuvo(CLIENTES if clientes is None else clientes),
    )


def test_index_exige_login(client):
    resposta = client.get("/rotas")
    assert resposta.status_code == 302
    assert "/login" in resposta.headers["Location"]


def test_operador_pode_ver(operador_client):
    """Só leitura — não é tela de admin."""
    assert operador_client.get("/rotas").status_code == 200


def test_index_sem_catalogo_convida_a_gerar(operador_client):
    corpo = operador_client.get("/rotas").get_data(as_text=True)

    assert "Nenhum catálogo gerado ainda" in corpo


def test_gerar_mostra_as_regioes_e_os_clientes(operador_client, monkeypatch):
    _preparar(monkeypatch)

    corpo = operador_client.post("/rotas/gerar", follow_redirects=True).get_data(
        as_text=True
    )

    assert "Savassi — Belo Horizonte" in corpo
    assert "Buritis — Belo Horizonte" in corpo
    assert "SEM BAIRRO" in corpo  # quem não tem bairro não some da tela


def test_exportar_sem_gerar_avisa(operador_client):
    corpo = operador_client.get("/rotas/exportar", follow_redirects=True).get_data(
        as_text=True
    )

    assert "Gere o catálogo antes" in corpo


def test_export_tem_as_tres_abas(operador_client, monkeypatch):
    _preparar(monkeypatch)
    operador_client.post("/rotas/gerar")

    resposta = operador_client.get("/rotas/exportar")

    assert resposta.status_code == 200
    wb = load_workbook(BytesIO(resposta.data))
    assert wb.sheetnames == ["Clientes por bairro", "Resumo por região", "Sem bairro"]
    assert [c.value for c in wb["Clientes por bairro"][1]][:4] == [
        "REGIÃO",
        "CONTA",
        "CLIENTE",
        "BAIRRO",
    ]
    assert wb["Sem bairro"].max_row == 2  # cabeçalho + o cliente sem bairro


def test_export_traz_exatamente_o_que_esta_na_tela(operador_client, monkeypatch):
    """O resultado fica na sessão: exportar não refaz a consulta, que
    leva minutos e poderia dar outro número."""
    _preparar(monkeypatch)
    operador_client.post("/rotas/gerar")

    # A plataforma "muda" depois de gerar; o export não pode mudar junto.
    _preparar(monkeypatch, contas=[_conta("9", "OUTRA COISA")], clientes=[])
    wb = load_workbook(BytesIO(operador_client.get("/rotas/exportar").data))

    contas = {
        wb["Clientes por bairro"].cell(row=linha, column=2).value
        for linha in range(2, 6)
    }
    assert "9" not in contas


# ---------- importação da planilha ----------


def test_importar_planilha_da_auvo_pela_tela(operador_client):
    arquivo = _xlsx_auvo(
        [["Código", "Nome", "Endereço"], ["500", "PADARIA DO ZE", ENDERECO_SAVASSI]]
    )

    corpo = operador_client.post(
        "/rotas/importar",
        data={"arquivo": (BytesIO(arquivo), "clientes.xlsx")},
        content_type="multipart/form-data",
        follow_redirects=True,
    ).get_data(as_text=True)

    assert "Planilha da Auvo importada" in corpo
    assert "1 com bairro" in corpo


def test_importar_sem_arquivo_avisa(operador_client):
    corpo = operador_client.post(
        "/rotas/importar",
        data={},
        content_type="multipart/form-data",
        follow_redirects=True,
    ).get_data(as_text=True)

    assert "Escolha o arquivo" in corpo


def test_arquivo_que_nao_e_planilha_e_recusado_com_explicacao(operador_client):
    corpo = operador_client.post(
        "/rotas/importar",
        data={"arquivo": (BytesIO(b"nao sou planilha"), "qualquer.xls")},
        content_type="multipart/form-data",
        follow_redirects=True,
    ).get_data(as_text=True)

    assert "HTML" in corpo  # explica o que fazer, não só "deu erro"


def test_importar_descarta_o_catalogo_antigo_da_sessao(operador_client, monkeypatch):
    """Senão a tela mostra o resultado de antes logo depois de importar —
    exatamente a confusão que este módulo já causou."""
    _preparar(monkeypatch)
    operador_client.post("/rotas/gerar")

    arquivo = _xlsx_auvo(
        [["Código", "Nome", "Endereço"], ["500", "PADARIA", ENDERECO_SAVASSI]]
    )
    corpo = operador_client.post(
        "/rotas/importar",
        data={"arquivo": (BytesIO(arquivo), "clientes.xlsx")},
        content_type="multipart/form-data",
        follow_redirects=True,
    ).get_data(as_text=True)

    assert "Nenhum catálogo gerado ainda" in corpo


def test_tela_mostra_o_que_ja_foi_importado(operador_client):
    arquivo = _xlsx_auvo(
        [["Código", "Nome", "Endereço"], ["500", "PADARIA", ENDERECO_SAVASSI]]
    )
    operador_client.post(
        "/rotas/importar",
        data={"arquivo": (BytesIO(arquivo), "clientes.xlsx")},
        content_type="multipart/form-data",
    )

    corpo = operador_client.get("/rotas").get_data(as_text=True)

    assert "Endereços importados" in corpo
    assert "Auvo" in corpo
