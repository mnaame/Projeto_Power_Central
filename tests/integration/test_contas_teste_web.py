"""Tela de contas em teste — o que protege é quem PODE apertar o botão,
e o que exatamente é gravado quando ele é apertado."""

from app.services import contas_teste_service as svc
from tests.integration.test_contas_teste_service import CONTAS, MENSAGEM, FakePortal


def _preparar(monkeypatch, portal=None):
    alvo = portal or FakePortal()
    monkeypatch.setattr(svc, "_criar_cliente", lambda config: alvo)
    return alvo


# ---------- quem pode ----------


def test_index_exige_login(client):
    assert client.get("/contas-teste").status_code == 302


def test_operador_nao_entra(operador_client):
    """Suprimir alarme não é operação de rotina."""
    assert operador_client.get("/contas-teste").status_code == 403


def test_operador_nao_aplica(operador_client):
    assert operador_client.post("/contas-teste/aplicar", data={}).status_code == 403


def test_admin_entra(admin_client):
    corpo = admin_client.get("/contas-teste").get_data(as_text=True)

    assert "Contas em Teste" in corpo
    assert "suprime alarme" in corpo.lower()  # o aviso está na cara


# ---------- preparar ----------


def test_preparar_mostra_as_contas_sem_gravar(admin_client, monkeypatch):
    portal = _preparar(monkeypatch)

    corpo = admin_client.post(
        "/contas-teste/preparar", data={"mensagem": MENSAGEM}, follow_redirects=True
    ).get_data(as_text=True)

    assert "SUPER NOSSO FLEMING FILIAL 420" in corpo
    assert portal.gravacoes == []


def test_preparar_mostra_as_nao_encontradas(admin_client, monkeypatch):
    _preparar(monkeypatch)

    corpo = admin_client.post(
        "/contas-teste/preparar", data={"mensagem": "420\n777"}, follow_redirects=True
    ).get_data(as_text=True)

    assert "Não encontradas" in corpo
    assert "777" in corpo


def test_preparar_mostra_as_ambiguas_sem_escolher(admin_client, monkeypatch):
    duplicado = CONTAS + [
        {"cue_iid": "9009", "cue_ncuenta": "0099", "cue_cnombre": "SUPER NOSSO OUTRO FILIAL 420"}
    ]
    _preparar(monkeypatch, FakePortal(duplicado))

    corpo = admin_client.post(
        "/contas-teste/preparar", data={"mensagem": "420"}, follow_redirects=True
    ).get_data(as_text=True)

    assert "Ambíguas" in corpo


# ---------- aplicar ----------


def test_aplicar_sem_a_palavra_de_confirmacao_nao_grava(admin_client, monkeypatch):
    portal = _preparar(monkeypatch)
    admin_client.post("/contas-teste/preparar", data={"mensagem": MENSAGEM})

    corpo = admin_client.post(
        "/contas-teste/aplicar",
        data={"cue_iid": ["9001"]},
        follow_redirects=True,
    ).get_data(as_text=True)

    assert portal.gravacoes == []
    assert "COLOCAR EM TESTE" in corpo


def test_aplicar_com_a_confirmacao_grava(admin_client, monkeypatch):
    portal = _preparar(monkeypatch)
    admin_client.post("/contas-teste/preparar", data={"mensagem": MENSAGEM})

    corpo = admin_client.post(
        "/contas-teste/aplicar",
        data={"cue_iid": ["9001", "9002"], "confirmacao": "COLOCAR EM TESTE"},
        follow_redirects=True,
    ).get_data(as_text=True)

    assert [g["cue_iid"] for g in portal.gravacoes] == ["9001", "9002"]
    assert "expira sozinha" in corpo


def test_so_entra_o_que_foi_marcado(admin_client, monkeypatch):
    portal = _preparar(monkeypatch)
    admin_client.post("/contas-teste/preparar", data={"mensagem": MENSAGEM})

    admin_client.post(
        "/contas-teste/aplicar",
        data={"cue_iid": ["9002"], "confirmacao": "COLOCAR EM TESTE"},
    )

    assert [g["cue_iid"] for g in portal.gravacoes] == ["9002"]


def test_conta_fora_da_previsualizacao_e_ignorada(admin_client, monkeypatch):
    """A sessão é a autorização; o formulário é só o recorte dela. Sem
    isto, um POST montado à mão colocaria em teste qualquer conta da
    base — inclusive uma que ninguém conferiu."""
    portal = _preparar(monkeypatch)
    admin_client.post("/contas-teste/preparar", data={"mensagem": MENSAGEM})

    admin_client.post(
        "/contas-teste/aplicar",
        data={"cue_iid": ["9999"], "confirmacao": "COLOCAR EM TESTE"},
        follow_redirects=True,
    )

    assert portal.gravacoes == []


def test_aplicar_sem_preparar_antes_nao_grava(admin_client, monkeypatch):
    """Pré-visualização é obrigatória: é o passo que separa "a lista da
    semana" de "silenciar a loja errada"."""
    portal = _preparar(monkeypatch)

    corpo = admin_client.post(
        "/contas-teste/aplicar",
        data={"cue_iid": ["9001"], "confirmacao": "COLOCAR EM TESTE"},
        follow_redirects=True,
    ).get_data(as_text=True)

    assert portal.gravacoes == []
    assert "Prepare a lista antes" in corpo


def test_falha_parcial_aparece_na_tela_com_o_motivo(admin_client, monkeypatch):
    _preparar(monkeypatch, FakePortal(erro_em={"9002"}))
    admin_client.post("/contas-teste/preparar", data={"mensagem": MENSAGEM})

    corpo = admin_client.post(
        "/contas-teste/aplicar",
        data={"cue_iid": ["9001", "9002"], "confirmacao": "COLOCAR EM TESTE"},
        follow_redirects=True,
    ).get_data(as_text=True)

    assert "1 conta(s) em teste" in corpo
    assert "9002" in corpo


def test_depois_de_aplicar_a_previsualizacao_some(admin_client, monkeypatch):
    """Senão dá para aplicar o mesmo lote duas vezes sem conferir de
    novo."""
    _preparar(monkeypatch)
    admin_client.post("/contas-teste/preparar", data={"mensagem": MENSAGEM})
    admin_client.post(
        "/contas-teste/aplicar",
        data={"cue_iid": ["9001"], "confirmacao": "COLOCAR EM TESTE"},
    )

    corpo = admin_client.get("/contas-teste").get_data(as_text=True)

    assert "Vão entrar em teste" not in corpo


# ---------- barra lateral e temas ----------


def test_rodape_da_barra_fica_fora_do_menu_que_rola(admin_client):
    """O menu passou de quinze itens e empurrou trocar tema, usuário e
    sair para fora da tela. O rodapé é irmão do `sidebar-nav`, não filho
    — é isso que o mantém alcançável em qualquer altura."""
    corpo = admin_client.get("/contas-teste").get_data(as_text=True)

    nav = corpo.index('class="sidebar-nav"')
    fim_nav = corpo.index("</nav>", nav)
    rodape = corpo.index('class="sidebar-footer"')

    assert rodape > fim_nav


def test_o_seletor_de_tema_esta_no_rodape(admin_client):
    corpo = admin_client.get("/contas-teste").get_data(as_text=True)
    rodape = corpo.index('class="sidebar-footer"')
    trecho = corpo[rodape : corpo.index("</aside>", rodape)]

    assert 'data-tema="light"' in trecho
    assert 'data-tema="preto"' in trecho
    assert 'data-tema="sepia"' in trecho
    assert "logout" in trecho  # sair continua ali


def test_tema_e_aplicado_antes_do_css(admin_client):
    """O app.js tem `defer`: aplicar o tema lá mostraria a tela clara por
    um instante antes de virar preta — a "piscada"."""
    corpo = admin_client.get("/contas-teste").get_data(as_text=True)

    assert corpo.index("power-central-theme") < corpo.index("css/tokens.css")
