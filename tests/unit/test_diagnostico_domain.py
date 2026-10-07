from app.domain import diagnostico as dom
from app.domain.diagnostico import ConfigDiagnostico

CFG = ConfigDiagnostico(
    disparos_limiar=5,
    bypass_limiar=3,
    comunicacao_limiar=4,
    codigos_comunicacao=("EPC", "FST"),
    codigos_painel_bateria=("_BT", "E41"),
    codigos_painel_ac=("E40", "POW"),
    codigos_painel_tamper=("TAM",),
)


def _evento(codigo, *, quando="2026-10-01T03:00:00", zona=""):
    """Madrugada de propósito: longe de arme/desarme, para o disparo não
    cair na exclusão de rotina de entrada/saída."""
    return {
        "rec_calarma": codigo,
        "rec_tfechahora": quando,
        "_zon_cdescripcion": zona,
        "rec_iid": f"{codigo}-{quando}-{zona}",
    }


def _disparos(quantidade, *, zona, hora_inicial=3):
    return [
        _evento("BUR", quando=f"2026-10-0{1 + i // 20}T{hora_inicial + i % 20:02d}:00:00", zona=zona)
        for i in range(quantidade)
    ]


# ---------- disparos recorrentes ----------


def test_disparos_acima_do_limiar_viram_achado_com_as_zonas():
    eventos = [*_disparos(6, zona="PORTAO SOCIAL"), *_disparos(4, zona="GARAGEM")]

    achados = dom.diagnosticar(eventos, cfg=CFG, dias=15)

    disparo = next(a for a in achados if a.titulo == "Disparos recorrentes")
    assert disparo.severidade == dom.SEVERIDADE_ALTA
    assert "10 disparo(s)" in disparo.detalhe
    assert "PORTAO SOCIAL (6)" in disparo.detalhe
    assert "GARAGEM (4)" in disparo.detalhe


def test_disparos_abaixo_do_limiar_nao_viram_achado():
    achados = dom.diagnosticar(_disparos(4, zona="SALA"), cfg=CFG, dias=15)

    assert [a.titulo for a in achados] == ["Sem problemas relevantes no período"]


def test_zona_de_panico_nao_conta_porque_a_regra_validada_exclui():
    """Não é regra deste módulo: vem do `domain/disparos.py`, e o teste
    existe para garantir que continuamos passando por lá."""
    achados = dom.diagnosticar(_disparos(9, zona="PANICO"), cfg=CFG, dias=15)

    assert [a.titulo for a in achados] == ["Sem problemas relevantes no período"]


def test_so_as_tres_maiores_zonas_sao_citadas():
    eventos = [
        *_disparos(6, zona="A"),
        *_disparos(5, zona="B"),
        *_disparos(4, zona="C"),
        *_disparos(3, zona="D"),
    ]

    detalhe = next(
        a for a in dom.diagnosticar(eventos, cfg=CFG, dias=15)
        if a.titulo == "Disparos recorrentes"
    ).detalhe

    assert "A (6)" in detalhe
    assert "B (5)" in detalhe
    assert "C (4)" in detalhe
    assert "D (3)" not in detalhe  # a quarta zona fica de fora


# ---------- bypass ----------


def test_zona_isolada_repetida_vira_achado():
    eventos = [_evento("BYP", zona="SALA") for _ in range(6)]

    achados = dom.diagnosticar(eventos, cfg=CFG, dias=15)

    bypass = next(a for a in achados if a.titulo == "Zona isolada repetida")
    assert "SALA isolada 6x" in bypass.detalhe
    assert bypass.severidade == dom.SEVERIDADE_MEDIA


def test_bypass_abaixo_do_limiar_fica_quieto():
    eventos = [_evento("BYP", zona="SALA") for _ in range(2)]

    assert [a.titulo for a in dom.diagnosticar(eventos, cfg=CFG, dias=15)] == [
        "Sem problemas relevantes no período"
    ]


def test_bypass_conta_por_zona_e_nao_no_total():
    """Duas zonas isoladas 2x cada não é zona com defeito — é uso normal."""
    eventos = [
        *[_evento("BYP", zona="SALA") for _ in range(2)],
        *[_evento("BYP", zona="GARAGEM") for _ in range(2)],
    ]

    assert [a.titulo for a in dom.diagnosticar(eventos, cfg=CFG, dias=15)] == [
        "Sem problemas relevantes no período"
    ]


# ---------- comunicação e painel ----------


def test_comunicacao_instavel_acima_do_limiar():
    eventos = [_evento("EPC") for _ in range(3)] + [_evento("FST") for _ in range(3)]

    achado = next(
        a for a in dom.diagnosticar(eventos, cfg=CFG, dias=15)
        if a.titulo == "Comunicação instável"
    )

    assert "6 queda(s)" in achado.detalhe


def test_falta_de_energia_basta_um_evento():
    achados = dom.diagnosticar([_evento("POW")], cfg=CFG, dias=15)

    ac = next(a for a in achados if a.titulo == "Falta de energia (AC)")
    assert ac.detalhe == "1 vez(es)"
    assert ac.severidade == dom.SEVERIDADE_MEDIA


def test_bateria_e_tamper_sao_severidade_alta():
    achados = dom.diagnosticar([_evento("_BT"), _evento("TAM")], cfg=CFG, dias=15)

    assert {a.titulo: a.severidade for a in achados} == {
        "Bateria baixa": dom.SEVERIDADE_ALTA,
        "Violação/tamper": dom.SEVERIDADE_ALTA,
    }


def test_codigo_fora_das_listas_e_ignorado():
    """Restauração ("voltou ao normal") fica de fora por construção: só é
    contado o que está nas listas de gatilho."""
    achados = dom.diagnosticar([_evento("RST"), _evento("E40R")], cfg=CFG, dias=15)

    assert [a.titulo for a in achados] == ["Sem problemas relevantes no período"]


# ---------- ordenação e formatação ----------


def test_achados_saem_do_mais_grave_para_o_menos():
    eventos = [
        *_disparos(6, zona="PORTAO"),  # alta
        _evento("POW"),                 # media
        *[_evento("BYP", zona="SALA") for _ in range(4)],  # media
    ]

    severidades = [a.severidade for a in dom.diagnosticar(eventos, cfg=CFG, dias=15)]

    assert severidades == sorted(severidades, reverse=True)


def test_formatacao_tem_titulo_e_uma_linha_por_achado():
    achados = dom.diagnosticar(
        [*_disparos(6, zona="PORTAO"), _evento("POW")], cfg=CFG, dias=15
    )

    texto = dom.formatar_diagnostico(
        achados, numero_conta="77", nome_cliente="CONDOMINIO MONDRIAN", dias=15
    )

    linhas = texto.splitlines()
    assert linhas[0] == "Diagnóstico — 77 CONDOMINIO MONDRIAN (últimos 15 dia(s))"
    assert sum(1 for l in linhas if l.startswith("- ")) == len(achados)


def test_sem_problemas_tambem_e_formatado():
    texto = dom.formatar_diagnostico(
        dom.diagnosticar([], cfg=CFG, dias=7),
        numero_conta="95", nome_cliente="LOJA", dias=7,
    )

    assert "Sem problemas relevantes" in texto


def test_truncagem_corta_os_menos_graves_e_mantem_o_pior():
    """Mensagem longa demais não pode esconder o problema grave — ele vem
    primeiro e é o último a sair."""
    muitos = [
        dom.Achado(severidade=dom.SEVERIDADE_ALTA, titulo="PIOR", detalhe="x"),
        *[
            dom.Achado(severidade=dom.SEVERIDADE_BAIXA, titulo=f"menor {i}", detalhe="y" * 200)
            for i in range(50)
        ],
    ]

    texto = dom.formatar_diagnostico(
        muitos, numero_conta="1", nome_cliente="X", dias=7, limite=600
    )

    assert len(texto) <= 600
    assert "PIOR" in texto
    assert "(...)" in texto
