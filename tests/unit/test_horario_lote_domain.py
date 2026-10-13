from app.domain import horario_lote as dom


# ---------- cálculo do novo fechamento ----------


def test_soma_simples():
    assert dom.novo_fechamento("18:00", 60) == ("19:00", False)


def test_soma_que_atravessa_a_hora():
    assert dom.novo_fechamento("18:45", 30) == ("19:15", False)


def test_fechamento_que_bate_meia_noite_nao_e_alterado():
    """23:00 + 1h = 00:00. Mudar isso exigiria mexer no DIA do fechamento,
    que é decisão sobre a grade do cliente — não conta de somar."""
    assert dom.novo_fechamento("23:00", 60) == (None, True)


def test_fechamento_que_passa_da_meia_noite_nao_e_alterado():
    assert dom.novo_fechamento("23:30", 60) == (None, True)


def test_ultimo_minuto_que_ainda_cabe():
    assert dom.novo_fechamento("22:59", 60) == ("23:59", False)


def test_delta_negativo_tambem_e_respeitado():
    assert dom.novo_fechamento("18:00", -60) == ("17:00", False)


def test_delta_negativo_que_passaria_do_inicio_do_dia_nao_altera():
    assert dom.novo_fechamento("00:30", -60) == (None, True)


def test_hora_ilegivel_nao_vira_palpite():
    """Não se escreve por cima do que não se entende."""
    assert dom.novo_fechamento("", 60) == (None, False)
    assert dom.novo_fechamento("ontem", 60) == (None, False)
    assert dom.novo_fechamento("99:99", 60) == (None, False)


def test_aceita_hora_com_segundos():
    assert dom.novo_fechamento("18:00:00", 60) == ("19:00", False)


# ---------- preparação das linhas ----------


def _linha(horario_id=7201, fechamento="18:00", abertura="06:00", dia=7):
    return {
        "Id": horario_id,
        "Name": "",
        "hor_iidcuenta": 9383,
        "hor_ndiaapertura": dia,
        "hor_choraapertura": abertura,
        "hor_ndiacierre": dia,
        "hor_choracierre": fechamento,
    }


def test_linhas_sao_classificadas_em_aplicar_e_manual():
    preparadas = dom.preparar_linhas(
        [_linha(1, "18:00"), _linha(2, "23:00"), _linha(3, "xx")],
        conta="118", nome="SHOPPING", delta_min=60,
    )

    assert [p.categoria for p in preparadas] == [
        dom.CATEGORIA_APLICAR, dom.CATEGORIA_MANUAL, dom.CATEGORIA_INVALIDO
    ]
    assert preparadas[0].depois == "19:00"
    assert preparadas[1].depois == ""  # manual não ganha destino automático
    assert preparadas[2].depois == ""


def test_linha_sem_id_e_descartada():
    """Sem Id não há o que gravar — melhor sumir do lote do que figurar
    como pendente e nunca poder ser aplicada."""
    assert dom.preparar_linhas([{"hor_choracierre": "18:00"}], conta="1", nome="X", delta_min=60) == []


def test_abertura_e_dias_ficam_intactos():
    preparada = dom.preparar_linhas(
        [_linha(1, "18:00", abertura="06:00", dia=3)], conta="1", nome="X", delta_min=60
    )[0]

    assert preparada.hora_abertura == "06:00"
    assert preparada.dia_abertura == 3
    assert preparada.dia_fechamento == 3


# ---------- corpo do PUT ----------


def test_corpo_do_put_so_muda_o_fechamento():
    original = _linha(7201, "18:00")

    corpo = dom.corpo_do_put(original, novo_fechamento_hhmm="19:00")

    assert corpo == {
        "Id": 7201,
        "Name": "",
        "hor_iidcuenta": 9383,
        "hor_ndiaapertura": 7,
        "hor_choraapertura": "06:00",
        "hor_ndiacierre": 7,
        "hor_choracierre": "19:00",
    }


def test_corpo_do_put_ignora_campo_extra_que_o_portal_devolver():
    """Mandar campo que o portal não espera é risco desnecessário numa
    chamada de escrita — o conjunto é o confirmado no HAR."""
    com_extra = {**_linha(), "campo_novo_qualquer": "x", "Observacao": "y"}

    corpo = dom.corpo_do_put(com_extra, novo_fechamento_hhmm="19:00")

    assert "campo_novo_qualquer" not in corpo
    assert set(corpo) == {
        "Id", "Name", "hor_iidcuenta", "hor_ndiaapertura",
        "hor_choraapertura", "hor_ndiacierre", "hor_choracierre",
    }
