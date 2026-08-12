from datetime import date

from app.domain.tarefas import esta_atrasada, semana_corrente


# ---------- semana_corrente ----------


def test_semana_corrente_segunda_a_domingo():
    # 2026-08-12 é uma quarta-feira
    inicio, fim = semana_corrente(date(2026, 8, 12))
    assert inicio == date(2026, 8, 10)  # segunda
    assert fim == date(2026, 8, 16)  # domingo


def test_semana_corrente_na_propria_segunda():
    inicio, fim = semana_corrente(date(2026, 8, 10))
    assert inicio == date(2026, 8, 10)
    assert fim == date(2026, 8, 16)


def test_semana_corrente_no_proprio_domingo():
    inicio, fim = semana_corrente(date(2026, 8, 16))
    assert inicio == date(2026, 8, 10)
    assert fim == date(2026, 8, 16)


# ---------- esta_atrasada ----------


def test_esta_atrasada_pendente_com_data_passada():
    assert esta_atrasada(date(2026, 8, 1), "pendente", hoje=date(2026, 8, 12)) is True


def test_esta_atrasada_pendente_com_data_hoje_nao_e_atrasada():
    assert esta_atrasada(date(2026, 8, 12), "pendente", hoje=date(2026, 8, 12)) is False


def test_esta_atrasada_feito_com_data_passada_nao_e_atrasada():
    assert esta_atrasada(date(2026, 8, 1), "feito", hoje=date(2026, 8, 12)) is False


def test_esta_atrasada_sem_data_nao_e_atrasada():
    assert esta_atrasada(None, "pendente", hoje=date(2026, 8, 12)) is False
