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


# ---------- "(NN) DESCRIÇÃO": o formato real do relatório ----------
#
# A primeira preventiva real saiu "Dispararam: 0 de 9" com as MESMAS nove
# zonas listadas logo abaixo como "dispararam e não estão no zoneamento".
# O relatório escreve número e nome juntos — "(26) IVP ENTRADA NOVA" — e o
# cadastro guarda "26" e "IVP ENTRADA NOVA" em campos separados.


def test_zona_do_relatorio_vem_com_o_numero_na_frente():
    """O caso que quebrou em produção, com os textos exatos dos dois
    lados."""
    zonas = [Zona("26", "IVP ENTRADA NOVA", "BUR")]

    resultado = dom.conferir(zonas, [_evento("(26) IVP ENTRADA NOVA")])

    assert [z.codigo for z in resultado.dispararam] == ["26"]
    assert resultado.faltam == []


def test_zona_prefixada_nao_aparece_tambem_como_extra():
    """O sintoma que denunciou o defeito: a mesma zona nas duas listas.
    Ficar só em "FALTAM" seria errado; ficar nas duas é errado E confuso,
    porque a resposta traz a prova de que ela disparou."""
    zonas = [Zona("26", "IVP ENTRADA NOVA", "BUR")]

    resultado = dom.conferir(zonas, [_evento("(26) IVP ENTRADA NOVA")])

    assert resultado.extras == []


def test_preventiva_completa_com_os_dados_reais_da_conta_36():
    zonas = [
        Zona("2", "BRINQUEDOTECA", "BUR"),
        Zona("3", "PORTÃO ENTRADA", "BUR"),
        Zona("4", "RECEPÇÃO", "BUR"),
        Zona("26", "IVP ENTRADA NOVA", "BUR"),
        Zona("30", "IVP CORREDOR", "BUR"),
    ]
    eventos = [
        _evento("(2) BRINQUEDOTECA"),
        _evento("(3) PORTÃO ENTRADA"),
        _evento("(4) RECEPÇÃO"),
        _evento("(26) IVP ENTRADA NOVA"),
        _evento("(30) IVP CORREDOR"),
    ]

    resultado = dom.conferir(zonas, eventos)

    assert len(resultado.dispararam) == 5
    assert resultado.completa


def test_casa_pelo_numero_quando_o_nome_nao_bate():
    """"(1) CORDENACAO" no painel, "COORDENAÇÃO" no cadastro: zona 1 é
    zona 1. Reprovar por causa da grafia manda o técnico voltar."""
    resultado = dom.conferir(
        [Zona("1", "COORDENAÇÃO", "BUR")], [_evento("(1) CORDENACAO")]
    )

    assert len(resultado.dispararam) == 1
    assert resultado.extras == []


def test_casamento_que_veio_so_do_numero_e_reportado():
    """É a única aposta deste módulo — se o número entre parênteses não
    for o código da zona, este é um OK errado. Mostrar é o que permite
    desmentir."""
    resultado = dom.conferir(
        [Zona("1", "COORDENAÇÃO", "BUR")], [_evento("(1) CORDENACAO")]
    )

    assert resultado.divergentes == ["1 COORDENAÇÃO = (1) CORDENACAO"]
    texto = dom.formatar_preventiva(
        resultado, numero_conta="36", nome_cliente="LOJA X", horas=36
    )
    assert "casou pelo número" in texto


def test_nome_igual_nao_e_reportado_como_divergente():
    """Senão a linha apareceria em toda preventiva e ninguém a leria."""
    resultado = dom.conferir(
        [Zona("26", "IVP ENTRADA NOVA", "BUR")], [_evento("(26) IVP ENTRADA NOVA")]
    )

    assert resultado.divergentes == []


def test_cadastro_prefixado_casa_com_evento_sem_prefixo():
    """O cruzamento é simétrico: não se sabe de antemão qual dos dois
    lados escreve o número."""
    resultado = dom.conferir(
        [Zona("26", "(26) IVP ENTRADA NOVA", "BUR")], [_evento("IVP ENTRADA NOVA")]
    )

    assert len(resultado.dispararam) == 1


def test_nomes_diferentes_do_mesmo_numero_sao_um_sensor_so():
    """O número é a identidade do sensor. Se a zona 4 aparecer com dois
    nomes — renomeada no meio da janela — contá-la duas vezes faz a lista
    de "não está no zoneamento" parecer inventada."""
    resultado = dom.conferir(
        [], [_evento("(4) RECEPÇÃO"), _evento("(4) RECEPCAO CAIXA")]
    )

    assert len(resultado.extras) == 1


def test_extra_prefixado_sai_com_o_rotulo_do_relatorio():
    """É o texto que se procura na plataforma para arrumar o zoneamento —
    normalizado, ele não é mais encontrável."""
    resultado = dom.conferir([], [_evento("(26) IVP ENTRADA NOVA")])

    assert resultado.extras == ["(26) IVP ENTRADA NOVA"]


def test_extras_saem_em_ordem_numerica():
    """Como texto, "(30)" vem antes de "(4)"."""
    eventos = [_evento("(30) IVP CORREDOR"), _evento("(4) RECEPÇÃO"), _evento("(2) X")]

    resultado = dom.conferir([], eventos)

    assert resultado.extras == ["(2) X", "(4) RECEPÇÃO", "(30) IVP CORREDOR"]


def test_so_numero_entre_parenteses_e_tratado_como_codigo():
    """Uma zona cadastrada "(FUNDOS) PORTA" não pode dar OK para a zona
    chamada só "PORTA". Se "(FUNDOS)" fosse descartado como se fosse
    código, as duas virariam a mesma coisa e um sensor que ninguém acionou
    sairia como testado — o pior erro deste relatório."""
    zonas = [Zona("7", "(FUNDOS) PORTA", "BUR"), Zona("1", "PORTA", "BUR")]

    resultado = dom.conferir(zonas, [_evento("(FUNDOS) PORTA")])

    assert [z.codigo for z in resultado.dispararam] == ["7"]
    assert [z.codigo for z in resultado.faltam] == ["1"]


def test_numero_do_relatorio_nao_casa_com_outra_zona():
    """Casar pelo número não pode virar casar com qualquer número: zona 3
    não dá OK porque a zona 30 disparou."""
    resultado = dom.conferir(
        [Zona("3", "PORTÃO ENTRADA", "BUR")], [_evento("(30) IVP CORREDOR")]
    )

    assert [z.codigo for z in resultado.faltam] == ["3"]


def test_partir_zona():
    assert dom.partir_zona("(26) IVP ENTRADA NOVA") == ("26", "IVP ENTRADA NOVA")
    assert dom.partir_zona("  (26)   IVP  ") == ("26", "IVP")
    assert dom.partir_zona("IVP ENTRADA NOVA") == ("", "IVP ENTRADA NOVA")
    assert dom.partir_zona("(SP1) PANICO") == ("", "(SP1) PANICO")
    assert dom.partir_zona("(5)") == ("5", "")
    assert dom.partir_zona("") == ("", "")


def test_zona_sem_nome_no_relatorio_casa_pelo_numero():
    """Painel que manda só "(5)". Sem o número, essa linha não casaria com
    nada e a zona 5 sairia como pendente."""
    resultado = dom.conferir([Zona("5", "FUNDOS", "BUR")], [_evento("(5)")])

    assert len(resultado.dispararam) == 1


def test_primeiro_disparo_mesmo_quando_a_primeira_linha_nao_tem_hora():
    """Linha com data que não se conseguiu interpretar não pode apagar a
    hora das outras."""
    resultado = dom.conferir(
        [Zona("1", "PORTA", "")],
        [_evento("(1) PORTA", ""), _evento("(1) PORTA", "2026-10-20T14:10:00")],
    )

    assert resultado.dispararam[0].quando == "2026-10-20T14:10:00"


def test_codigo_nao_numerico_e_especial_mesmo_fora_dos_prefixos():
    """O critério principal é ser não-numérico; os prefixos são a rede de
    segurança, não a regra. Uma zona "AX1" é tão não-física quanto uma
    "SP1", e contá-la como pendência criaria um "faltam" que nunca
    zera."""
    zonas = [Zona("AX1", "SIRENE EXTERNA", ""), Zona("1", "PORTA", "")]

    resultado = dom.conferir(zonas, [], prefixos_especiais=("SP", "NO"))

    assert [z.codigo for z in resultado.ignoradas] == ["AX1"]
    assert [z.codigo for z in resultado.faltam] == ["1"]
