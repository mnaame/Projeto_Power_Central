from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.domain.tarefas import semana_corrente
from app.extensions import db
from app.models.tarefa import Tarefa

FUSO = ZoneInfo("America/Sao_Paulo")


def _tarefa(user, **overrides):
    dados = {
        "user_id": user.id,
        "titulo": "Tarefa de teste",
        "horizonte": "dia",
        "data": date.today(),
    }
    dados.update(overrides)
    tarefa = Tarefa(**dados)
    db.session.add(tarefa)
    db.session.commit()
    return tarefa


# ---------- permissões ----------


def test_index_requer_login(client):
    resposta = client.get("/tarefas", follow_redirects=False)
    assert resposta.status_code == 302
    assert "/auth/login" in resposta.headers["Location"]


def test_operador_acessa_index(operador_client):
    assert operador_client.get("/tarefas").status_code == 200


# ---------- criar (adição rápida) ----------


def test_criar_tarefa_no_dia(app, operador_client, operador_user):
    resposta = operador_client.post(
        "/tarefas/criar", data={"titulo": "Ligar pro cliente", "horizonte": "dia"}
    )
    assert resposta.status_code == 302
    tarefa = Tarefa.query.filter_by(user_id=operador_user.id).one()
    assert tarefa.titulo == "Ligar pro cliente"
    assert tarefa.horizonte == "dia"
    assert tarefa.data == date.today()


def test_criar_tarefa_fixa_sem_data(app, operador_client, operador_user):
    operador_client.post("/tarefas/criar", data={"titulo": "Revisar de-para", "horizonte": "fixa"})
    tarefa = Tarefa.query.filter_by(user_id=operador_user.id).one()
    assert tarefa.data is None


def test_criar_aparece_na_listagem(app, operador_client):
    operador_client.post("/tarefas/criar", data={"titulo": "Tarefa unica XYZ", "horizonte": "dia"})
    resposta = operador_client.get("/tarefas")
    assert "Tarefa unica XYZ".encode() in resposta.data


def test_criar_titulo_vazio_nao_cria(app, operador_client, operador_user):
    operador_client.post("/tarefas/criar", data={"titulo": "   ", "horizonte": "dia"})
    assert Tarefa.query.filter_by(user_id=operador_user.id).count() == 0


def test_criar_horizonte_invalido_400(operador_client):
    resposta = operador_client.post(
        "/tarefas/criar", data={"titulo": "x", "horizonte": "invalido"}
    )
    assert resposta.status_code == 400


# ---------- concluir ----------


def test_concluir_alterna_status(app, operador_client, operador_user):
    tarefa = _tarefa(operador_user)
    resposta = operador_client.post(f"/tarefas/{tarefa.id}/concluir")
    assert resposta.status_code == 302
    db.session.refresh(tarefa)
    assert tarefa.status == "feito"

    operador_client.post(f"/tarefas/{tarefa.id}/concluir")
    db.session.refresh(tarefa)
    assert tarefa.status == "pendente"


# ---------- mover ----------


def test_mover_para_semana(app, operador_client, operador_user):
    tarefa = _tarefa(operador_user, horizonte="dia")
    resposta = operador_client.post(f"/tarefas/{tarefa.id}/mover", data={"horizonte": "semana"})
    assert resposta.status_code == 302
    db.session.refresh(tarefa)
    assert tarefa.horizonte == "semana"


def test_mover_horizonte_invalido_400(app, operador_client, operador_user):
    tarefa = _tarefa(operador_user)
    resposta = operador_client.post(f"/tarefas/{tarefa.id}/mover", data={"horizonte": "invalido"})
    assert resposta.status_code == 400


# ---------- editar ----------


def test_editar_get_mostra_form_preenchido(app, operador_client, operador_user):
    tarefa = _tarefa(operador_user, titulo="Titulo original")
    resposta = operador_client.get(f"/tarefas/{tarefa.id}/editar")
    assert resposta.status_code == 200
    assert b"Titulo original" in resposta.data


def test_editar_post_atualiza(app, operador_client, operador_user):
    tarefa = _tarefa(operador_user)
    resposta = operador_client.post(
        f"/tarefas/{tarefa.id}/editar",
        data={
            "titulo": "Título atualizado",
            "descricao": "nova descrição",
            "horizonte": "fixa",
            "data": "",
            "prioridade": "alta",
        },
    )
    assert resposta.status_code == 302
    db.session.refresh(tarefa)
    assert tarefa.titulo == "Título atualizado"
    assert tarefa.horizonte == "fixa"
    assert tarefa.prioridade == "alta"


# ---------- excluir ----------


def test_excluir_remove(app, operador_client, operador_user):
    tarefa = _tarefa(operador_user)
    tarefa_id = tarefa.id
    resposta = operador_client.post(f"/tarefas/{tarefa_id}/excluir")
    assert resposta.status_code == 302
    assert db.session.get(Tarefa, tarefa_id) is None


# ---------- isolamento por dono ----------


def test_id_inexistente_404(operador_client):
    assert operador_client.post("/tarefas/999999/concluir").status_code == 404


def test_operador_nao_conclui_tarefa_de_outro(app, admin_client, operador_user):
    tarefa = _tarefa(operador_user)
    resposta = admin_client.post(f"/tarefas/{tarefa.id}/concluir")
    assert resposta.status_code == 403
    db.session.refresh(tarefa)
    assert tarefa.status == "pendente"


def test_operador_nao_move_tarefa_de_outro(app, admin_client, operador_user):
    tarefa = _tarefa(operador_user, horizonte="dia")
    resposta = admin_client.post(f"/tarefas/{tarefa.id}/mover", data={"horizonte": "semana"})
    assert resposta.status_code == 403


def test_operador_nao_edita_tarefa_de_outro(app, admin_client, operador_user):
    tarefa = _tarefa(operador_user)
    assert admin_client.get(f"/tarefas/{tarefa.id}/editar").status_code == 403


def test_operador_nao_exclui_tarefa_de_outro(app, admin_client, operador_user):
    tarefa = _tarefa(operador_user)
    resposta = admin_client.post(f"/tarefas/{tarefa.id}/excluir")
    assert resposta.status_code == 403
    assert db.session.get(Tarefa, tarefa.id) is not None


def test_cada_usuario_ve_so_as_proprias_na_listagem(app, admin_client, admin_user, operador_user):
    _tarefa(operador_user, titulo="Tarefa do operador")
    _tarefa(admin_user, titulo="Tarefa do admin")
    resposta = admin_client.get("/tarefas")
    assert b"Tarefa do admin" in resposta.data
    assert b"Tarefa do operador" not in resposta.data


# ---------- atrasadas não somem ----------


def test_tarefa_atrasada_continua_visivel(app, operador_client, operador_user):
    _tarefa(operador_user, horizonte="dia", data=date.today() - timedelta(days=5), status="pendente")
    resposta = operador_client.get("/tarefas")
    assert b"is-atrasada" in resposta.data


def test_tarefa_semana_nao_atrasa_antes_da_semana_acabar(app, operador_client, operador_user):
    """Regressão: tarefa criada na segunda não pode aparecer como
    atrasada na terça da MESMA semana — só depois que a semana acabar."""
    inicio_semana, fim_semana = semana_corrente(date.today())
    _tarefa(operador_user, horizonte="semana", data=inicio_semana, status="pendente")
    resposta = operador_client.get("/tarefas")
    assert b"is-atrasada" not in resposta.data


def test_tarefa_semana_atrasa_so_depois_que_a_semana_acaba(app, operador_client, operador_user):
    inicio_semana, _ = semana_corrente(date.today())
    semana_passada = inicio_semana - timedelta(days=7)
    _tarefa(operador_user, horizonte="semana", data=semana_passada, status="pendente")
    resposta = operador_client.get("/tarefas")
    assert b"is-atrasada" in resposta.data


# ---------- histórico ----------


def test_historico_requer_login(client):
    resposta = client.get("/tarefas/historico", follow_redirects=False)
    assert resposta.status_code == 302
    assert "/auth/login" in resposta.headers["Location"]


def test_historico_vazio(operador_client):
    resposta = operador_client.get("/tarefas/historico")
    assert resposta.status_code == 200
    assert "Nenhuma tarefa concluída ainda".encode() in resposta.data


def test_historico_mostra_concluida_de_qualquer_dia(app, operador_client, operador_user):
    tarefa = _tarefa(
        operador_user,
        titulo="Tarefa feita semana passada",
        status="feito",
        concluido_em=datetime.now(FUSO) - timedelta(days=10),
    )
    resposta = operador_client.get("/tarefas/historico")
    assert "Tarefa feita semana passada".encode() in resposta.data


def test_historico_nao_mostra_pendente(app, operador_client, operador_user):
    _tarefa(operador_user, titulo="Ainda pendente", status="pendente")
    resposta = operador_client.get("/tarefas/historico")
    assert "Ainda pendente".encode() not in resposta.data


def test_historico_ordena_mais_recente_primeiro(app, operador_client, operador_user):
    agora = datetime.now(FUSO)
    _tarefa(operador_user, titulo="Mais antiga", status="feito", concluido_em=agora - timedelta(days=5))
    _tarefa(operador_user, titulo="Mais recente", status="feito", concluido_em=agora - timedelta(days=1))
    resposta = operador_client.get("/tarefas/historico")
    texto = resposta.data.decode()
    assert texto.index("Mais recente") < texto.index("Mais antiga")


def test_historico_so_mostra_as_proprias(app, admin_client, admin_user, operador_user):
    _tarefa(operador_user, titulo="Feita pelo operador", status="feito", concluido_em=datetime.now(FUSO))
    _tarefa(admin_user, titulo="Feita pelo admin", status="feito", concluido_em=datetime.now(FUSO))
    resposta = admin_client.get("/tarefas/historico")
    assert "Feita pelo admin".encode() in resposta.data
    assert "Feita pelo operador".encode() not in resposta.data


def test_historico_reabrir_volta_pendente(app, operador_client, operador_user):
    tarefa = _tarefa(
        operador_user, titulo="Reabrir essa", status="feito", concluido_em=datetime.now(FUSO)
    )
    resposta = operador_client.post(f"/tarefas/{tarefa.id}/concluir", follow_redirects=True)
    assert resposta.status_code == 200
    db.session.refresh(tarefa)
    assert tarefa.status == "pendente"
    assert tarefa.concluido_em is None


def test_historico_paginacao(app, operador_client, operador_user):
    agora = datetime.now(FUSO)
    for i in range(35):
        _tarefa(
            operador_user,
            titulo=f"Concluida {i}",
            status="feito",
            concluido_em=agora - timedelta(minutes=i),
        )
    pagina1 = operador_client.get("/tarefas/historico")
    assert "Página 1 de 2".encode() in pagina1.data

    pagina2 = operador_client.get("/tarefas/historico?pagina=2")
    assert pagina2.status_code == 200
    assert "Página 2 de 2".encode() in pagina2.data
