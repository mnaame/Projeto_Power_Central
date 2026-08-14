from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.domain.disparos import (
    MOTIVO_CICLO_CURTO,
    MOTIVO_ROTINA_ARME,
    MOTIVO_ROTINA_DESARME,
    MOTIVO_ZONA_IGNORADA,
    avaliar_disparos_da_conta,
    consolidar_clientes,
    zona_ignorada,
)

FUSO = ZoneInfo("America/Sao_Paulo")
BASE = datetime(2026, 7, 18, 22, 0, 0, tzinfo=FUSO)


def _fmt(dt):
    return dt.strftime("%m/%d/%Y %I:%M:%S %p")


def _evento(codigo, quando, conta="9385", zona="(28) IVP ENTRADA RM", operador="7", rec_iid="100"):
    return {
        "rec_iid": rec_iid,
        "rec_iidcuenta": conta,
        "cue_cnombre": f"CLIENTE {conta}",
        "rec_calarma": codigo,
        "rec_tfechahora": _fmt(quando),
        "_zon_cdescripcion": zona,
        "rec_ioperador": operador,
    }


# ---------- zona_ignorada ----------


def test_zona_panico_ignorada_com_e_sem_acento():
    assert zona_ignorada("(02) BOTAO PANICO") is True
    assert zona_ignorada("(02) BOTÃO PÂNICO") is True
    assert zona_ignorada("(02) botão pânico escritório") is True
    assert zona_ignorada("(28) IVP ENTRADA RM") is False


def test_zonas_ignoradas_configuraveis():
    assert zona_ignorada("(05) TESTE MANUTENCAO", zonas_ignoradas=("MANUTENCAO",)) is True
    assert zona_ignorada("(02) BOTAO PANICO", zonas_ignoradas=("MANUTENCAO",)) is False


# ---------- avaliar_disparos_da_conta (aceites B.3) ----------


def test_disparo_5min_apos_arme_e_excluido():
    eventos = [
        _evento("CLO", BASE),
        _evento("BUR", BASE + timedelta(minutes=3)),  # rotina de saída
        _evento("BUR", BASE + timedelta(minutes=8)),  # fora da janela -> válido
    ]
    avaliados = avaliar_disparos_da_conta(eventos)
    assert [d.valido for d in avaliados] == [False, True]
    assert avaliados[0].motivo_exclusao == MOTIVO_ROTINA_ARME


def test_disparo_5min_antes_de_desarme_e_excluido():
    eventos = [
        _evento("BUR", BASE),                          # 4 min antes do OPN -> rotina
        _evento("BUR", BASE - timedelta(minutes=10)),  # longe do desarme -> válido
        _evento("OPN", BASE + timedelta(minutes=4)),
    ]
    avaliados = avaliar_disparos_da_conta(eventos)
    assert [d.valido for d in avaliados] == [False, True]
    assert avaliados[0].motivo_exclusao == MOTIVO_ROTINA_DESARME


def test_todos_os_codigos_de_arme_e_desarme_contam():
    for arme in ("CLO", "CLV", "ROP"):
        avaliados = avaliar_disparos_da_conta(
            [_evento(arme, BASE), _evento("BUR", BASE + timedelta(minutes=2))]
        )
        assert avaliados[0].valido is False, arme

    for desarme in ("OPN", "OPV", "RCL"):
        avaliados = avaliar_disparos_da_conta(
            [_evento("BUR", BASE), _evento(desarme, BASE + timedelta(minutes=2))]
        )
        assert avaliados[0].valido is False, desarme


def test_disparo_em_zona_de_panico_e_excluido():
    avaliados = avaliar_disparos_da_conta(
        [_evento("BUR", BASE, zona="(02) BOTAO PANICO")]
    )
    assert avaliados[0].valido is False
    assert avaliados[0].motivo_exclusao == MOTIVO_ZONA_IGNORADA


# ---------- ciclo curto (arme seguido de desarme em até 15 min) ----------


def test_disparo_no_meio_de_ciclo_curto_e_excluido():
    # arme às 22:00, desarme às 22:14 (ciclo de 14 min) — o disparo fica
    # 7 min longe de cada ponta, fora das janelas de 5 min de cada lado,
    # mas deve ser descartado porque o ciclo inteiro foi curto.
    eventos = [
        _evento("CLO", BASE),
        _evento("BUR", BASE + timedelta(minutes=7)),
        _evento("OPN", BASE + timedelta(minutes=14)),
    ]
    avaliados = avaliar_disparos_da_conta(eventos)
    assert avaliados[0].valido is False
    assert avaliados[0].motivo_exclusao == MOTIVO_CICLO_CURTO


def test_disparo_fora_de_ciclo_curto_continua_valido_mesmo_perto_do_arme():
    # arme às 22:00, disparo 10 min depois, mas o desarme só vem 4h
    # depois — não é um ciclo curto (período armado normal), então o
    # disparo tem que continuar contando (poderia ser invasão real).
    eventos = [
        _evento("CLO", BASE),
        _evento("BUR", BASE + timedelta(minutes=10)),
        _evento("OPN", BASE + timedelta(hours=4)),
    ]
    avaliados = avaliar_disparos_da_conta(eventos)
    assert avaliados[0].valido is True


def test_ciclo_curto_com_rcl_como_desarme():
    eventos = [
        _evento("ROP", BASE),
        _evento("BUR", BASE + timedelta(minutes=6)),
        _evento("RCL", BASE + timedelta(minutes=12)),
    ]
    avaliados = avaliar_disparos_da_conta(eventos)
    assert avaliados[0].valido is False
    assert avaliados[0].motivo_exclusao == MOTIVO_CICLO_CURTO


def test_ciclo_de_16min_nao_e_curto():
    eventos = [
        _evento("CLO", BASE),
        _evento("BUR", BASE + timedelta(minutes=8)),
        _evento("OPN", BASE + timedelta(minutes=16)),
    ]
    avaliados = avaliar_disparos_da_conta(eventos)
    assert avaliados[0].valido is True


def test_disparo_isolado_e_valido():
    avaliados = avaliar_disparos_da_conta([_evento("BUR", BASE)])
    assert avaliados[0].valido is True
    assert avaliados[0].motivo_exclusao is None


def test_arme_de_outro_momento_nao_exclui():
    eventos = [
        _evento("CLO", BASE - timedelta(hours=2)),
        _evento("BUR", BASE),
    ]
    avaliados = avaliar_disparos_da_conta(eventos)
    assert avaliados[0].valido is True


# ---------- consolidar_clientes (aceites B.3/B.4) ----------


def test_contagem_nao_agrupa_disparos():
    eventos = [
        _evento("BUR", BASE + timedelta(minutes=i), rec_iid=str(100 + i)) for i in range(30)
    ]
    clientes = consolidar_clientes(eventos)
    assert len(clientes) == 1
    assert clientes[0].quantidade == 30


def test_ocorrencia_recorrente_a_partir_do_limite():
    eventos = [
        _evento("BUR", BASE + timedelta(minutes=i), rec_iid=str(i)) for i in range(15)
    ]
    clientes = consolidar_clientes(eventos)
    assert clientes[0].ocorrencia == "ALEATORIO E RECORRENTE"

    poucos = consolidar_clientes(eventos[:14])
    assert poucos[0].ocorrencia == "ALEATORIO"


def test_limite_recorrente_configuravel():
    eventos = [_evento("BUR", BASE + timedelta(minutes=i), rec_iid=str(i)) for i in range(5)]
    clientes = consolidar_clientes(eventos, limite_recorrente=5)
    assert clientes[0].ocorrencia == "ALEATORIO E RECORRENTE"


def test_zonas_distintas_sem_repetir():
    eventos = [
        _evento("BUR", BASE, zona="(28) IVP ENTRADA RM", rec_iid="1"),
        _evento("BUR", BASE + timedelta(minutes=1), zona="(28) IVP ENTRADA RM", rec_iid="2"),
        _evento("BUR", BASE + timedelta(minutes=2), zona="(30) IVP FUNDOS", rec_iid="3"),
    ]
    clientes = consolidar_clientes(eventos)
    assert clientes[0].zonas == ("(28) IVP ENTRADA RM", "(30) IVP FUNDOS")


def test_ids_atendidos_do_mais_recente_para_o_mais_antigo():
    eventos = [
        _evento("BUR", BASE, rec_iid="1", operador="7"),
        _evento("BUR", BASE + timedelta(minutes=5), rec_iid="2", operador="0"),  # não atendido
        _evento("BUR", BASE + timedelta(minutes=10), rec_iid="3", operador="9"),
    ]
    clientes = consolidar_clientes(eventos)
    assert clientes[0].ids_eventos_atendidos == ("3", "1")


def test_clientes_separados_por_conta_e_ordenados_por_quantidade():
    eventos = [
        _evento("BUR", BASE, conta="111", rec_iid="1"),
        _evento("BUR", BASE + timedelta(minutes=1), conta="222", rec_iid="2"),
        _evento("BUR", BASE + timedelta(minutes=2), conta="222", rec_iid="3"),
    ]
    clientes = consolidar_clientes(eventos)
    assert [c.conta_id for c in clientes] == ["222", "111"]
    assert [c.quantidade for c in clientes] == [2, 1]


def test_horarios_todos_os_disparos_do_mais_antigo_para_o_mais_recente():
    eventos = [
        _evento("BUR", BASE + timedelta(minutes=10), rec_iid="1"),
        _evento("BUR", BASE, rec_iid="2"),
        _evento("BUR", BASE + timedelta(minutes=5), rec_iid="3"),
    ]
    clientes = consolidar_clientes(eventos)
    assert clientes[0].horarios == (
        BASE,
        BASE + timedelta(minutes=5),
        BASE + timedelta(minutes=10),
    )


def test_horarios_nao_inclui_disparo_invalido():
    eventos = [
        _evento("CLO", BASE, conta="111"),
        _evento("BUR", BASE + timedelta(minutes=2), conta="111"),  # rotina, inválido
        _evento("BUR", BASE + timedelta(minutes=20), conta="111"),  # válido
    ]
    clientes = consolidar_clientes(eventos)
    assert clientes[0].horarios == (BASE + timedelta(minutes=20),)


def test_cliente_sem_disparo_valido_fica_fora():
    eventos = [
        _evento("CLO", BASE, conta="111"),
        _evento("BUR", BASE + timedelta(minutes=2), conta="111"),  # rotina
        _evento("BUR", BASE, conta="222", rec_iid="9"),
    ]
    clientes = consolidar_clientes(eventos)
    assert [c.conta_id for c in clientes] == ["222"]


def test_filtrar_para_janela_corta_bur_da_folga_mas_mantem_armes():
    from app.domain.disparos import filtrar_para_janela

    desde = BASE
    hasta = BASE + timedelta(hours=1)
    eventos = [
        _evento("CLO", desde - timedelta(minutes=4)),               # folga: mantém (arme)
        _evento("BUR", desde - timedelta(minutes=2), rec_iid="1"),  # folga: corta (disparo)
        _evento("BUR", desde + timedelta(minutes=30), rec_iid="2"), # dentro: mantém
        _evento("OPN", hasta + timedelta(minutes=3)),               # folga: mantém (desarme)
        _evento("BUR", hasta + timedelta(minutes=2), rec_iid="3"),  # folga: corta
    ]

    filtrados = filtrar_para_janela(eventos, desde=desde, hasta=hasta)
    codigos = [e["rec_calarma"] for e in filtrados]
    assert codigos == ["CLO", "BUR", "OPN"]
    assert filtrados[1]["rec_iid"] == "2"
