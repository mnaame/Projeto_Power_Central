from datetime import datetime
from zoneinfo import ZoneInfo

from app.domain.atendimentos import (
    ABERTO,
    DESCARTADO,
    INCLUIDO,
    analisar_timeline,
    prefixo_do_dia,
    processar_atendimento,
    resolucao_indica_arme,
)

FUSO = ZoneInfo("America/Sao_Paulo")
# 18/07/2026 é um sábado
DATA_EVENTO = datetime(2026, 7, 18, 21, 30, 0, tzinfo=FUSO)


def _passo(hora, acao, observacao="", codigo="", operador="MARIA"):
    return {
        "etl_tFechaHora": hora,
        "etl_cAccion": acao,
        "etl_cObservacion": observacao,
        "etl_iAccionCode": codigo,
        "ope_cnombre": operador,
    }


def _timeline_fechada_manual(observacao_comentario="Cliente vai ativar mais tarde"):
    return [
        _passo("7/18/2026 9:30:00 PM", "Inicio", "Evento recebido na Central"),
        _passo("7/18/2026 9:32:10 PM", "IngresoComentarios", "--- PROCEDIMENTO PADRAO NYE"),
        _passo("7/18/2026 9:35:00 PM", "IngresoComentarios", observacao_comentario),
        _passo("7/18/2026 9:41:05 PM", "Procesar", "Evento processado", codigo="122"),
    ]


def _processar(timeline, **overrides):
    kwargs = {
        "data_evento": DATA_EVENTO,
        "conta": "0004",
        "cliente": "VILLEFORT TROPICAL",
        "evento": "NYE",
        "timeline": timeline,
    }
    kwargs.update(overrides)
    return processar_atendimento(**kwargs)


# ---------- analisar_timeline ----------


def test_inicio_fechamento_e_monitor():
    analise = analisar_timeline(_timeline_fechada_manual())

    assert analise.inicio == datetime(2026, 7, 18, 21, 30, 0, tzinfo=FUSO)
    assert analise.fechamento == datetime(2026, 7, 18, 21, 41, 5, tzinfo=FUSO)
    assert analise.fechado_por_autoproceso is False
    assert analise.monitor == "MARIA"


def test_situacao_ignora_comentarios_de_procedimento():
    analise = analisar_timeline(_timeline_fechada_manual("Falei com o responsável"))
    assert analise.situacao == "Falei com o responsável"


def test_situacao_usa_ultimo_comentario_manual_antes_do_fechamento():
    timeline = _timeline_fechada_manual("Primeiro contato sem sucesso")
    timeline.insert(
        3, _passo("7/18/2026 9:38:00 PM", "IngresoComentarios", "Segundo contato: resolvido")
    )
    analise = analisar_timeline(timeline)
    assert analise.situacao == "Segundo contato: resolvido"


def test_comentario_depois_do_fechamento_nao_conta():
    timeline = _timeline_fechada_manual("Comentário válido")
    timeline.append(
        _passo("7/18/2026 9:55:00 PM", "IngresoComentarios", "Comentário tardio")
    )
    analise = analisar_timeline(timeline)
    assert analise.situacao == "Comentário válido"


def test_fechamento_por_autoproceso_define_monitor_automatico():
    timeline = [
        _passo("7/18/2026 9:30:00 PM", "Inicio", "Evento recebido na Central"),
        _passo("7/18/2026 9:50:00 PM", "Autoproceso", "Fechado por CLO", operador=""),
    ]
    analise = analisar_timeline(timeline)
    assert analise.fechado_por_autoproceso is True
    assert analise.monitor == "Automático"


def test_chamada_atendida_define_momento_da_ligacao():
    # timeline real reconstruída do evento MIL-0172 (21/07/2026 03:26:58) —
    # chamada às 03:44:59 (18min01s depois do início) e fechamento às
    # 03:45:31 (18min33s depois), validado contra os valores preenchidos
    # manualmente ("18M00S" / "00H18M32S", diferença de ~1s por arredondamento).
    timeline = [
        _passo("7/21/2026 3:26:58 AM", "Inicio", "Evento recebido na Central"),
        _passo("7/21/2026 3:27:20 AM", "IngresoComentarios", "--- PROCEDIMENTO --- [DEALER: MIL]"),
        _passo(
            "7/21/2026 3:44:59 AM",
            "LlamadoTelefonico",
            "(*84 -31987388855 Chamada Atendida - Bem Sucedida) [00:00:51]",
        ),
        _passo("7/21/2026 3:45:31 AM", "IngresoComentarios", "Local com trabalho noturno."),
        _passo("7/21/2026 3:45:31 AM", "Procesar", "Processa tudo - processado", codigo="122"),
    ]
    analise = analisar_timeline(timeline)
    assert analise.chamada == datetime(2026, 7, 21, 3, 44, 59, tzinfo=FUSO)
    assert analise.fechamento == datetime(2026, 7, 21, 3, 45, 31, tzinfo=FUSO)


def test_chamada_nao_atendida_nao_conta():
    timeline = [
        _passo("7/21/2026 3:26:58 AM", "Inicio", "Evento recebido na Central"),
        _passo("7/21/2026 3:30:00 AM", "LlamadoTelefonico", "Chamada não atendida"),
        _passo("7/21/2026 3:45:31 AM", "Procesar", "processado", codigo="122"),
    ]
    assert analisar_timeline(timeline).chamada is None


def test_fechamento_por_codigo_133():
    timeline = [
        _passo("7/18/2026 9:30:00 PM", "Inicio", "Evento recebido na Central"),
        _passo("7/18/2026 9:45:00 PM", "Procesar", "fechado", codigo="133"),
    ]
    assert analisar_timeline(timeline).fechamento is not None


def test_sem_chamada_registrada_fica_none():
    analise = analisar_timeline(_timeline_fechada_manual())
    assert analise.chamada is None


def test_fechamento_por_texto_processado():
    timeline = [
        _passo("7/18/2026 9:30:00 PM", "Inicio", "Evento recebido na Central"),
        _passo("7/18/2026 9:47:00 PM", "Fin", "Evento Processado pelo operador"),
    ]
    analise = analisar_timeline(timeline)
    assert analise.fechamento is not None


def test_sem_fechamento_evento_em_aberto():
    timeline = [
        _passo("7/18/2026 9:30:00 PM", "Inicio", "Evento recebido na Central"),
        _passo("7/18/2026 9:35:00 PM", "IngresoComentarios", "Tentando contato"),
    ]
    analise = analisar_timeline(timeline)
    assert analise.fechamento is None
    assert analise.monitor is None


# ---------- resolucao_indica_arme ----------


def test_resolucao_ativado_indica_arme():
    assert resolucao_indica_arme("Sistema ativado pelo cliente") is True


def test_negacao_nao_indica_arme():
    # Critério de aceite: "ainda não foi ativado" APARECE no relatório.
    assert resolucao_indica_arme("alarme ainda não foi ativado") is False


def test_negacao_sem_acento_tambem_vale():
    assert resolucao_indica_arme("ainda nao foi ativado") is False


def test_armado_remotamente_indica_arme():
    assert resolucao_indica_arme("Armado remotamente pela central") is True


def test_arme_apos_negacao_de_outra_coisa_ainda_conta():
    # a negação precisa estar perto do termo; longe dela, conta como arme
    assert resolucao_indica_arme("não atendeu de primeira, depois confirmou e foi ativado") is True


def test_termos_configuraveis():
    assert resolucao_indica_arme("cliente armou tudo", termos_arme=("armou",)) is True
    assert resolucao_indica_arme("Sistema ativado", termos_arme=("armou",)) is False


# ---------- processar_atendimento (aceites) ----------


def test_evento_fechado_com_ativado_e_descartado_com_motivo():
    resultado = _processar(_timeline_fechada_manual("Sistema ativado pelo responsável"))
    assert resultado.status == DESCARTADO
    assert "armou" in resultado.motivo_descarte


def test_evento_com_ainda_nao_foi_ativado_e_incluido():
    resultado = _processar(_timeline_fechada_manual("alarme ainda não foi ativado"))
    assert resultado.status == INCLUIDO


def test_fechamento_automatico_descartado_por_padrao():
    timeline = [
        _passo("7/18/2026 9:30:00 PM", "Inicio", "Evento recebido na Central"),
        _passo("7/18/2026 9:50:00 PM", "Autoproceso", "Fechado por CLO", operador=""),
    ]
    resultado = _processar(timeline)
    assert resultado.status == DESCARTADO
    assert "utom" in resultado.motivo_descarte  # "automático"
    assert resultado.monitor == "Automático"


def test_fechamento_automatico_incluido_quando_configurado():
    timeline = [
        _passo("7/18/2026 9:30:00 PM", "Inicio", "Evento recebido na Central"),
        _passo("7/18/2026 9:50:00 PM", "Autoproceso", "Fechado", operador=""),
    ]
    resultado = _processar(timeline, incluir_automaticos=True)
    assert resultado.status == INCLUIDO


def test_evento_aberto_marcado_e_fora_por_padrao():
    timeline = [_passo("7/18/2026 9:30:00 PM", "Inicio", "Evento recebido na Central")]
    resultado = _processar(timeline)
    assert resultado.status == ABERTO

    incluido = _processar(timeline, incluir_abertos=True)
    assert incluido.status == INCLUIDO


def test_tempo_no_formato_padronizado():
    resultado = _processar(_timeline_fechada_manual())
    assert resultado.tempo_atendimento == "00H11M05S"


def test_situacao_recebe_prefixo_do_dia():
    resultado = _processar(_timeline_fechada_manual("Cliente avisado"))
    assert resultado.situacao == "SAB: Cliente avisado"


def test_prefixo_do_dia_cobre_a_semana():
    # 13/07/2026 é segunda-feira
    assert prefixo_do_dia(datetime(2026, 7, 13, tzinfo=FUSO)) == "SEG"
    assert prefixo_do_dia(datetime(2026, 7, 17, tzinfo=FUSO)) == "SEX"
    assert prefixo_do_dia(datetime(2026, 7, 19, tzinfo=FUSO)) == "DOM"
