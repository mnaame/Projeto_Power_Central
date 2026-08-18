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


# ---------- esta_atrasada — horizonte "dia" ----------


def test_esta_atrasada_dia_pendente_com_data_passada():
    assert esta_atrasada(date(2026, 8, 1), "pendente", horizonte="dia", hoje=date(2026, 8, 12)) is True


def test_esta_atrasada_dia_pendente_com_data_hoje_nao_e_atrasada():
    assert esta_atrasada(date(2026, 8, 12), "pendente", horizonte="dia", hoje=date(2026, 8, 12)) is False


def test_esta_atrasada_dia_feito_com_data_passada_nao_e_atrasada():
    assert esta_atrasada(date(2026, 8, 1), "feito", horizonte="dia", hoje=date(2026, 8, 12)) is False


def test_esta_atrasada_dia_sem_data_nao_e_atrasada():
    assert esta_atrasada(None, "pendente", horizonte="dia", hoje=date(2026, 8, 12)) is False


# ---------- esta_atrasada — horizonte "semana" (bug real corrigido) ----------


def test_esta_atrasada_semana_criada_segunda_nao_atrasa_na_terca_da_mesma_semana():
    # 2026-08-10 é segunda; 2026-08-11 é terça da MESMA semana — não pode
    # atrasar (era exatamente o bug relatado).
    assert (
        esta_atrasada(date(2026, 8, 10), "pendente", horizonte="semana", hoje=date(2026, 8, 11))
        is False
    )


def test_esta_atrasada_semana_nao_atrasa_em_nenhum_dia_da_mesma_semana():
    criada_segunda = date(2026, 8, 10)
    for dia_da_semana in range(7):  # segunda a domingo da mesma semana
        hoje = date(2026, 8, 10 + dia_da_semana)
        assert (
            esta_atrasada(criada_segunda, "pendente", horizonte="semana", hoje=hoje) is False
        ), f"não devia atrasar em {hoje}"


def test_esta_atrasada_semana_atrasa_só_na_semana_seguinte():
    criada_segunda = date(2026, 8, 10)  # semana 10-16/08
    proxima_segunda = date(2026, 8, 17)
    assert (
        esta_atrasada(criada_segunda, "pendente", horizonte="semana", hoje=proxima_segunda)
        is True
    )


def test_esta_atrasada_semana_feito_nunca_atrasa():
    assert (
        esta_atrasada(date(2026, 8, 1), "feito", horizonte="semana", hoje=date(2026, 8, 20))
        is False
    )


# ---------- esta_atrasada — horizonte "fixa" (nunca atrasa por aqui) ----------


def test_esta_atrasada_fixa_sem_data_nunca_atrasa():
    assert esta_atrasada(None, "pendente", horizonte="fixa", hoje=date(2026, 8, 12)) is False
