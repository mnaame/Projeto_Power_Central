from datetime import date, timedelta

from app.extensions import db
from app.models.tarefa import Tarefa


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
    assert b"atrasada" in resposta.data
