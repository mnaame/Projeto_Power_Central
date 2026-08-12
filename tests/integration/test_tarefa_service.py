from datetime import date, datetime, timedelta

import pytest

from app.domain.dates import FUSO_HORARIO
from app.extensions import db
from app.models.tarefa import Tarefa
from app.services import tarefa_service

# 2026-08-12 é uma quarta-feira da semana 2026-08-10 (seg) a 2026-08-16 (dom).
HOJE = date(2026, 8, 12)


def _tarefa(user, **overrides):
    dados = {
        "user_id": user.id,
        "titulo": "Tarefa de teste",
        "horizonte": "dia",
        "data": HOJE,
    }
    dados.update(overrides)
    tarefa = Tarefa(**dados)
    db.session.add(tarefa)
    db.session.commit()
    return tarefa


# ---------- listar_dia ----------


def test_listar_dia_mostra_tarefa_de_hoje(app, admin_user):
    _tarefa(admin_user, data=HOJE)
    itens = tarefa_service.listar_dia(admin_user.id, referencia=HOJE)
    assert len(itens) == 1


def test_listar_dia_mostra_pendente_atrasada(app, admin_user):
    _tarefa(admin_user, data=HOJE - timedelta(days=3), status="pendente")
    itens = tarefa_service.listar_dia(admin_user.id, referencia=HOJE)
    assert len(itens) == 1


def test_listar_dia_nao_mostra_feita_atrasada(app, admin_user):
    _tarefa(admin_user, data=HOJE - timedelta(days=3), status="feito")
    itens = tarefa_service.listar_dia(admin_user.id, referencia=HOJE)
    assert itens == []


def test_listar_dia_nao_mostra_tarefa_de_outro_horizonte(app, admin_user):
    _tarefa(admin_user, horizonte="semana", data=HOJE)
    itens = tarefa_service.listar_dia(admin_user.id, referencia=HOJE)
    assert itens == []


def test_listar_dia_nao_mostra_tarefa_de_outro_usuario(app, admin_user, operador_user):
    _tarefa(operador_user, data=HOJE)
    itens = tarefa_service.listar_dia(admin_user.id, referencia=HOJE)
    assert itens == []


# ---------- listar_semana ----------


def test_listar_semana_mostra_tarefa_dentro_da_semana(app, admin_user):
    _tarefa(admin_user, horizonte="semana", data=date(2026, 8, 15))
    itens = tarefa_service.listar_semana(admin_user.id, referencia=HOJE)
    assert len(itens) == 1


def test_listar_semana_nao_mostra_tarefa_de_outra_semana(app, admin_user):
    _tarefa(admin_user, horizonte="semana", data=date(2026, 8, 20), status="pendente")
    itens = tarefa_service.listar_semana(admin_user.id, referencia=HOJE)
    assert itens == []


def test_listar_semana_mostra_pendente_de_semana_anterior_como_atrasada(app, admin_user):
    _tarefa(admin_user, horizonte="semana", data=date(2026, 8, 1), status="pendente")
    itens = tarefa_service.listar_semana(admin_user.id, referencia=HOJE)
    assert len(itens) == 1


# ---------- listar_fixas ----------


def test_listar_fixas_so_mostra_pendentes(app, admin_user):
    _tarefa(admin_user, horizonte="fixa", data=None, status="pendente")
    _tarefa(admin_user, horizonte="fixa", data=None, status="feito")
    itens = tarefa_service.listar_fixas(admin_user.id)
    assert len(itens) == 1
    assert itens[0].status == "pendente"


# ---------- listar_concluidas_hoje ----------


def test_listar_concluidas_hoje_filtra_por_data_de_conclusao(app, admin_user):
    concluida_hoje = _tarefa(admin_user, status="feito")
    concluida_hoje.concluido_em = datetime(2026, 8, 12, 15, 0, tzinfo=FUSO_HORARIO)
    concluida_ontem = _tarefa(admin_user, status="feito")
    concluida_ontem.concluido_em = datetime(2026, 8, 11, 15, 0, tzinfo=FUSO_HORARIO)
    db.session.commit()

    itens = tarefa_service.listar_concluidas_hoje(admin_user.id, referencia=HOJE)
    assert [t.id for t in itens] == [concluida_hoje.id]


# ---------- contar_dia ----------


def test_contar_dia_conta_pendentes_e_atrasadas(app, admin_user):
    _tarefa(admin_user, data=HOJE, status="pendente")
    _tarefa(admin_user, data=HOJE - timedelta(days=1), status="pendente")
    _tarefa(admin_user, data=HOJE, status="feito")

    contagem = tarefa_service.contar_dia(admin_user.id, referencia=HOJE)
    assert contagem == {"pendentes": 2, "atrasadas": 1}


# ---------- criar ----------


def test_criar_dia_usa_data_de_hoje(app, admin_user):
    tarefa = tarefa_service.criar(
        user_id=admin_user.id, titulo="Ligar pro cliente", horizonte="dia", referencia=HOJE
    )
    db.session.commit()
    assert tarefa.data == HOJE
    assert tarefa.status == "pendente"
    assert tarefa.prioridade == "media"


def test_criar_fixa_fica_sem_data(app, admin_user):
    tarefa = tarefa_service.criar(
        user_id=admin_user.id, titulo="Revisar de-para", horizonte="fixa", referencia=HOJE
    )
    db.session.commit()
    assert tarefa.data is None


def test_criar_titulo_vazio_levanta_erro(app, admin_user):
    with pytest.raises(ValueError):
        tarefa_service.criar(user_id=admin_user.id, titulo="   ", horizonte="dia")


# ---------- atualizar ----------


def test_atualizar_troca_campos(app, admin_user):
    tarefa = _tarefa(admin_user)
    tarefa_service.atualizar(
        tarefa,
        titulo="Novo título",
        descricao="detalhes",
        horizonte="fixa",
        data=None,
        prioridade="alta",
    )
    db.session.commit()
    assert tarefa.titulo == "Novo título"
    assert tarefa.descricao == "detalhes"
    assert tarefa.horizonte == "fixa"
    assert tarefa.prioridade == "alta"


def test_atualizar_titulo_vazio_levanta_erro(app, admin_user):
    tarefa = _tarefa(admin_user)
    with pytest.raises(ValueError):
        tarefa_service.atualizar(
            tarefa, titulo="", descricao=None, horizonte="dia", data=HOJE, prioridade="media"
        )


# ---------- alternar_status ----------


def test_alternar_status_conclui_e_grava_data(app, admin_user):
    tarefa = _tarefa(admin_user)
    tarefa_service.alternar_status(tarefa)
    db.session.commit()
    assert tarefa.status == "feito"
    assert tarefa.concluido_em is not None


def test_alternar_status_desmarca_e_limpa_data(app, admin_user):
    tarefa = _tarefa(admin_user, status="feito", concluido_em=datetime.now(FUSO_HORARIO))
    tarefa_service.alternar_status(tarefa)
    db.session.commit()
    assert tarefa.status == "pendente"
    assert tarefa.concluido_em is None


# ---------- mover ----------


def test_mover_para_dia_ajusta_data_para_hoje(app, admin_user):
    tarefa = _tarefa(admin_user, horizonte="semana", data=date(2026, 8, 15))
    tarefa_service.mover(tarefa, novo_horizonte="dia", referencia=HOJE)
    db.session.commit()
    assert tarefa.horizonte == "dia"
    assert tarefa.data == HOJE


def test_mover_para_semana_mantem_data_se_ja_na_semana(app, admin_user):
    tarefa = _tarefa(admin_user, horizonte="dia", data=date(2026, 8, 15))
    tarefa_service.mover(tarefa, novo_horizonte="semana", referencia=HOJE)
    db.session.commit()
    assert tarefa.data == date(2026, 8, 15)


def test_mover_para_semana_ajusta_data_se_fora_da_semana(app, admin_user):
    tarefa = _tarefa(admin_user, horizonte="dia", data=date(2026, 7, 1))
    tarefa_service.mover(tarefa, novo_horizonte="semana", referencia=HOJE)
    db.session.commit()
    assert tarefa.data == HOJE


def test_mover_para_fixa_mantem_data(app, admin_user):
    tarefa = _tarefa(admin_user, horizonte="dia", data=HOJE)
    tarefa_service.mover(tarefa, novo_horizonte="fixa", referencia=HOJE)
    db.session.commit()
    assert tarefa.horizonte == "fixa"
    assert tarefa.data == HOJE


# ---------- excluir ----------


def test_excluir_remove_do_banco(app, admin_user):
    tarefa = _tarefa(admin_user)
    tarefa_id = tarefa.id
    tarefa_service.excluir(tarefa)
    db.session.commit()
    assert db.session.get(Tarefa, tarefa_id) is None
