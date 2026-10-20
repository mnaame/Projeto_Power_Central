"""Conferência da preventiva: cruzar o zoneamento com o que disparou.

O erro que importa aqui tem direção: dizer **FALTA para uma zona que
disparou** manda o técnico voltar a uma loja pronta e ensina a equipe a
desconfiar do relatório. O contrário (dar OK de graça) é pior ainda, e os
dois têm teste.
"""

from app.domain import preventiva as dom
from app.domain.zoneamento import Zona


def _evento(zona, quando="2026-10-20T14:30:00"):
    return {"zona": zona, "quando": quando}


ZONAS = [
    Zona("1", "PORTA SALA", "NYR"),
    Zona("2", "INFRA SALA", "BUR"),
    Zona("5", "FUNDOS", "BUR"),
    Zona("10", "LATERAL", "BUR"),
    Zona("SP1", "SOS-PANICO", "PAN"),
]


# ---------- o cruzamento ----------


def test_zona_que_disparou_entra_em_OK():
    resultado = dom.conferir(ZONAS, [_evento("PORTA SALA")])

    assert [z.codigo for z in resultado.dispararam] == ["1"]


def test_zona_que_nao_disparou_entra_em_FALTAM():
    resultado = dom.conferir(ZONAS, [_evento("PORTA SALA")])

    assert [z.codigo for z in resultado.faltam] == ["2", "5", "10"]


def test_acento_e_caixa_nao_reprovam_a_zona():
    """O cadastro grava "Infra Sala" e o evento chega "INFRA SALA".
    Comparar cru reprovaria a zona e mandaria o técnico de volta."""
    zonas = [Zona("1", "Pátio Lateral", "BUR")]

    resultado = dom.conferir(zonas, [_evento("PATIO LATERAL")])

    assert resultado.faltam == []


def test_espaco_duplicado_nao_reprova_a_zona():
    resultado = dom.conferir([Zona("2", "INFRA SALA", "")], [_evento("INFRA  SALA")])

    assert len(resultado.dispararam) == 1


def test_qualquer_evento_com_zona_conta():
    """Uma porta magnética gera NYR, não BUR. Filtrar por um código só
    reportaria como "falta" um sensor que disparou — e este módulo nem
    olha o código, de propósito."""
    resultado = dom.conferir([Zona("1", "PORTA", "NYR")], [_evento("PORTA")])

    assert len(resultado.dispararam) == 1


def test_zona_que_disparou_e_nao_esta_no_cadastro_aparece():
    """Zoneamento desatualizado. Some da tela se ninguém mostrar."""
    resultado = dom.conferir(ZONAS, [_evento("DEPOSITO VELHO")])

    assert resultado.extras == ["DEPOSITO VELHO"]


def test_guarda_o_PRIMEIRO_disparo_de_cada_zona():
    """O export vem em ordem decrescente; a hora útil é a do primeiro
    acionamento, não a do último."""
    resultado = dom.conferir(
        [Zona("1", "PORTA", "")],
        [_evento("PORTA", "2026-10-20T14:30:00"), _evento("PORTA", "2026-10-20T14:10:00")],
    )

    assert resultado.dispararam[0].quando == "2026-10-20T14:10:00"


def test_evento_sem_zona_e_ignorado():
    """Arme, desarme e teste periódico não trazem zona."""
    resultado = dom.conferir(ZONAS, [_evento(""), _evento("   ")])

    assert resultado.dispararam == []
    assert resultado.extras == []


# ---------- zonas especiais ----------


def test_zona_de_codigo_nao_numerico_nao_conta_como_pendencia():
    """Pânico e incêndio não se aciona em rotina. Contá-los faria todo
    relatório terminar com um "faltam" permanente — e um alerta que nunca
    zera é um alerta que ninguém lê."""
    resultado = dom.conferir(ZONAS, [])

    assert [z.codigo for z in resultado.ignoradas] == ["SP1"]
    assert "SP1" not in [z.codigo for z in resultado.faltam]


def test_especial_nao_entra_no_total_de_fisicas():
    resultado = dom.conferir(ZONAS, [])

    assert resultado.total_fisicas == 4  # 5 zonas, menos a SP1


def test_prefixo_especial_configuravel():
    zonas = [Zona("9", "TESTE", ""), Zona("1", "PORTA", "")]

    resultado = dom.conferir(zonas, [], prefixos_especiais=("9",))

    assert [z.codigo for z in resultado.ignoradas] == ["9"]


def test_zona_sem_codigo_e_tratada_como_especial():
    """Sem código não dá para dizer se é sensor físico — e chutar que é
    criaria uma pendência que nunca se resolve."""
    resultado = dom.conferir([Zona("", "SEM CODIGO", "")], [])

    assert len(resultado.ignoradas) == 1


# ---------- ordem ----------


def test_ordena_por_numero_e_nao_por_texto():
    """Como texto, "10" vem antes de "2" — e a lista é conferida contra a
    loja na ordem dos sensores."""
    resultado = dom.conferir(ZONAS, [])

    assert [z.codigo for z in resultado.faltam] == ["1", "2", "5", "10"]


# ---------- o texto ----------


def test_texto_traz_a_contagem_e_as_duas_listas():
    resultado = dom.conferir(ZONAS, [_evento("PORTA SALA"), _evento("INFRA SALA")])

    texto = dom.formatar_preventiva(
        resultado, numero_conta="95", nome_cliente="LOJA X", horas=12
    )

    assert "Dispararam: 2 de 4 zonas físicas" in texto
    assert "OK: 1 PORTA SALA, 2 INFRA SALA" in texto
    assert "FALTAM (2): 5 FUNDOS, 10 LATERAL" in texto
    assert "SP1 SOS-PANICO" in texto


def test_texto_diz_quando_a_preventiva_esta_completa():
    zonas = [Zona("1", "PORTA", "")]

    texto = dom.formatar_preventiva(
        dom.conferir(zonas, [_evento("PORTA")]),
        numero_conta="95", nome_cliente="LOJA X", horas=12,
    )

    assert "preventiva completa" in texto


def test_conta_sem_zona_fisica_nao_finge_conferencia():
    """"Dispararam 0 de 0" pareceria falha do técnico."""
    texto = dom.formatar_preventiva(
        dom.conferir([Zona("SP1", "PANICO", "")], []),
        numero_conta="95", nome_cliente="LOJA X", horas=12,
    )

    assert "não tem zona física cadastrada" in texto


def test_horario_sai_curto_quando_pedido():
    resultado = dom.conferir(
        [Zona("1", "PORTA", "")], [_evento("PORTA", "2026-10-20T14:32:00")]
    )

    texto = dom.formatar_preventiva(
        resultado, numero_conta="95", nome_cliente="X", horas=12, com_horario=True
    )

    assert "(14:32)" in texto


def test_codigo_nao_numerico_e_especial_mesmo_fora_dos_prefixos():
    """O critério principal é ser não-numérico; os prefixos são a rede de
    segurança, não a regra. Uma zona "AX1" é tão não-física quanto uma
    "SP1", e contá-la como pendência criaria um "faltam" que nunca
    zera."""
    zonas = [Zona("AX1", "SIRENE EXTERNA", ""), Zona("1", "PORTA", "")]

    resultado = dom.conferir(zonas, [], prefixos_especiais=("SP", "NO"))

    assert [z.codigo for z in resultado.ignoradas] == ["AX1"]
    assert [z.codigo for z in resultado.faltam] == ["1"]
