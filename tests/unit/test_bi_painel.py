"""O que a tela do BI diz — e, principalmente, o que ela não deixa o
leitor concluir errado.

O defeito que gerou este módulo: "133 intervenções", "40% que melhorou" e
"506,4 disparos evitados" lado a lado, com denominadores diferentes. O
40% era 4 de 10. Os testes aqui travam as três decisões que consertam
isso — percentual sempre com o "de quantos", loja como unidade da
manchete, e nenhuma falsa precisão.
"""

from datetime import datetime, timedelta

from app.domain import bi_painel as dom
from app.domain.dates import FUSO_HORARIO

AGORA = datetime(2026, 10, 20, 12, 0, tzinfo=FUSO_HORARIO)


class Visita:
    """Mesma superfície que `BiIntervencao` — o domínio lê por atributo."""

    def __init__(
        self, conta="0095", nome="LOJA X", antes=1.0, depois=0.5,
        classificacao="MELHOROU", dias=15, marco=AGORA, parcial=False,
    ):
        self.conta_power = conta
        self.nome_loja = nome
        self.antes_por_dia = antes
        self.depois_por_dia = depois
        self.classificacao = classificacao
        self.dias_depois = dias
        self.marco = marco
        self.parcial = parcial


def _lojas(visitas, melhora=20.0, piora=20.0):
    return dom.lojas_por_resultado(
        visitas, limiar_melhora_pct=melhora, limiar_piora_pct=piora
    )


# ---------- a unidade da manchete é a LOJA ----------


def test_visitas_repetidas_na_mesma_loja_viram_uma_linha():
    """Senão a loja mais problemática — que é a mais visitada — domina a
    estatística e aparece cinco vezes no "melhorou"."""
    visitas = [
        Visita(marco=AGORA - timedelta(days=d), antes=2.0, depois=0.4) for d in (5, 20, 35)
    ]

    lojas = _lojas(visitas)

    assert len(lojas) == 1
    assert lojas[0].visitas == 3


def test_visita_sem_base_nao_dilui_o_antes_da_loja():
    """O erro que o painel inteiro existe para não cometer. Uma janela em
    que a loja não disparava entraria como "antes = 0" e puxaria a média
    para baixo, fazendo uma loja que PIOROU aparecer como melhorada."""
    visitas = [
        Visita(antes=1.0, depois=2.0, classificacao="PIOROU", marco=AGORA),
        Visita(antes=0.0, depois=0.0, classificacao="SEM_BASE", marco=AGORA - timedelta(days=30)),
        Visita(antes=0.0, depois=0.0, classificacao="SEM_BASE", marco=AGORA - timedelta(days=60)),
    ]

    lojas = _lojas(visitas)

    assert lojas[0].antes_por_dia == 1.0
    assert lojas[0].classificacao == "PIOROU"


def test_loja_so_com_visitas_sem_base_fica_de_fora():
    assert _lojas([Visita(antes=0.0, depois=0.0, classificacao="SEM_BASE")]) == []


def test_depois_e_ponderado_pelos_dias_medidos():
    """Uma visita de ontem tem 1 dia medido e uma de um mês atrás tem 15.
    Média simples daria a cada uma o mesmo peso, e a mais recente — a com
    menos evidência — decidiria a classificação da loja."""
    visitas = [
        Visita(antes=2.0, depois=0.0, dias=15, marco=AGORA - timedelta(days=30)),
        Visita(antes=2.0, depois=4.0, dias=1, marco=AGORA),
    ]

    lojas = _lojas(visitas)

    # (0*15 + 4*1) / 16 = 0,25 — e não a média simples, 2,0.
    assert round(lojas[0].depois_por_dia, 3) == 0.25


def test_classificacao_da_loja_respeita_os_limiares_do_run():
    visitas = [Visita(antes=1.0, depois=0.85)]

    assert _lojas(visitas, melhora=20.0)[0].classificacao == "ESTAVEL"
    assert _lojas(visitas, melhora=10.0)[0].classificacao == "MELHOROU"


def test_lista_abre_pelo_que_precisa_de_acao():
    """Piorou primeiro; dentro do grupo, quem dispara mais hoje. É a
    ordem em que se age, não a alfabética."""
    visitas = [
        Visita(conta="1", nome="MELHOROU", antes=2.0, depois=0.1),
        Visita(conta="2", nome="PIOROU POUCO", antes=1.0, depois=1.5),
        Visita(conta="3", nome="PIOROU MUITO", antes=1.0, depois=4.0),
        Visita(conta="4", nome="ESTAVEL", antes=1.0, depois=1.0),
    ]

    nomes = [loja.nome_loja for loja in _lojas(visitas)]

    assert nomes == ["PIOROU MUITO", "PIOROU POUCO", "ESTAVEL", "MELHOROU"]


def test_loja_parcial_quando_qualquer_visita_ainda_nao_fechou():
    visitas = [Visita(parcial=False), Visita(parcial=True, marco=AGORA - timedelta(days=1))]

    assert _lojas(visitas)[0].parcial is True


def test_situacao_sai_com_icone_alem_da_cor():
    """Cor de status sozinha não carrega significado — daltonismo,
    impressão, tema preto."""
    loja = _lojas([Visita(antes=2.0, depois=0.1)])[0]

    assert loja.rotulo_situacao == "Melhorou"
    assert loja.icone_situacao


# ---------- o "de quantos" ----------


def test_placar_traz_o_total_junto_do_numero():
    visitas = [
        Visita(conta="1", antes=2.0, depois=0.1),
        Visita(conta="2", antes=1.0, depois=4.0),
        Visita(conta="3", antes=1.0, depois=1.0),
    ]

    marcador = dom.placar(_lojas(visitas))

    assert (marcador.melhorou, marcador.total) == (1, 3)
    assert round(marcador.pct_melhorou) == 33


def test_percentual_sem_base_nenhuma_e_vazio_e_nao_zero():
    """"0%" leria como fracasso do técnico; o certo é "não dá para
    comparar"."""
    assert dom.placar([]).pct_melhorou is None


# ---------- sem falsa precisão ----------


def test_disparos_evitados_perde_a_casa_decimal():
    assert dom.disparos_evitados(506.4).valor == 506
    assert dom.disparos_evitados(506.4).direcao == "menos"


def test_disparos_evitados_negativo_vira_disparos_a_MAIS():
    """Um sinal de menos num número grande passa batido; a palavra não."""
    evitados = dom.disparos_evitados(-37.2)

    assert (evitados.valor, evitados.direcao) == (37, "mais")
    assert "a MAIS" in evitados.texto


def test_disparos_evitados_perto_de_zero_nao_finge_resultado():
    assert dom.disparos_evitados(0.4).direcao == "neutro"


# ---------- de onde vêm os números ----------


def _resumo(**extra):
    base = {
        "total_intervencoes": 133, "sem_vinculo": 16, "sem_data": 0,
        "melhorou": 4, "piorou": 2, "estavel": 4, "sem_base": 123,
    }
    base.update(extra)
    return base


def test_funil_comeca_nas_ordens_concluidas_de_verdade():
    """O "133" já exclui as sem vínculo. Começar o funil nele faria o
    "− 16" parecer que sai de dentro dos 133."""
    etapas = {e.rotulo: e.valor for e in dom.funil(_resumo(), lojas=[])}

    assert etapas["Ordens concluídas no período"] == 149
    assert etapas["Intervenções analisadas"] == 133


def test_funil_fecha_a_conta_ate_as_lojas():
    visitas = [Visita(conta=str(n), antes=2.0, depois=0.1) for n in range(4)]
    visitas += [Visita(conta="9", antes=1.0, depois=4.0)]

    etapas = {e.rotulo: e.valor for e in dom.funil(_resumo(), lojas=_lojas(visitas))}

    assert etapas["Intervenções com base"] == 10  # 133 − 123
    assert etapas["Lojas distintas (visitas repetidas somadas)"] == 5
    assert etapas["Lojas que melhoraram"] == 4


def test_funil_omite_a_linha_de_sem_data_quando_nao_houve():
    """Linha zerada num funil é ruído: parece que algo se perdeu ali."""
    rotulos = [e.rotulo for e in dom.funil(_resumo(sem_data=0), lojas=[])]

    assert "sem data de conclusão" not in rotulos


def test_funil_mostra_a_linha_de_sem_data_quando_houve():
    rotulos = [e.rotulo for e in dom.funil(_resumo(sem_data=3), lojas=[])]

    assert "sem data de conclusão" in rotulos


# ---------- a frase ----------


def _frase(**kwargs):
    base = dict(
        tecnico="Alfredo", total_intervencoes=133, lojas=[],
        evitados=dom.disparos_evitados(506.4), cronicos=6,
    )
    base.update(kwargs)
    return dom.frase_resumo(**base)


def test_frase_traduz_o_painel_inteiro():
    visitas = [Visita(conta=str(n), antes=2.0, depois=0.1) for n in range(4)]
    visitas += [Visita(conta="8", antes=1.0, depois=4.0), Visita(conta="9", antes=1.0, depois=9.0)]
    visitas += [Visita(conta=f"e{n}", antes=1.0, depois=1.0) for n in range(4)]

    texto = _frase(lojas=_lojas(visitas))

    assert "Alfredo fez 133 manutenções" in texto
    assert "Nas 10 lojas que dava para comparar" in texto
    assert "caíram em 4, pioraram em 2 e ficaram iguais em 4" in texto
    assert "~506 disparos a menos" in texto
    assert "6 lojas seguem crônicas" in texto


def test_frase_nao_lista_grupo_vazio():
    """"pioraram em 0" é ruído que faz o leitor procurar o zero."""
    texto = _frase(lojas=_lojas([Visita(antes=2.0, depois=0.1)]))

    assert "pioraram em 0" not in texto
    assert "caíram em 1" in texto


def test_frase_sem_base_de_comparacao_explica_em_vez_de_dar_zero():
    texto = _frase(lojas=[])

    assert "não houve base de comparação" in texto
    assert "0%" not in texto


def test_frase_sem_intervencao_nenhuma():
    texto = _frase(total_intervencoes=0)

    assert "não houve manutenção concluída" in texto


def test_frase_sem_tecnico_filtrado_fala_da_equipe():
    assert "a equipe fez" in _frase(tecnico="", total_intervencoes=5)


def test_frase_avisa_quando_os_disparos_aumentaram():
    texto = _frase(evitados=dom.disparos_evitados(-80.0), lojas=[])

    assert "a MAIS" in texto


def test_frase_no_singular_quando_e_uma_loja_so():
    texto = _frase(lojas=_lojas([Visita(antes=2.0, depois=0.1)]), cronicos=1)

    assert "Na 1 loja" in texto or "1 loja que dava para comparar" in texto
    assert "1 loja segue crônica." in texto


# ---------- a série semanal ----------


def test_semana_sem_visita_entra_na_serie_sem_barra():
    """Pular a semana encolheria o eixo do tempo calado; desenhar uma
    barra zerada diria "zero disparos", que é diferente de "ninguém foi
    medido"."""
    visitas = [
        Visita(marco=AGORA - timedelta(days=21), depois=1.0),
        Visita(marco=AGORA, depois=2.0),
    ]

    serie = dom.semanas(visitas)

    assert len(serie) == 4
    assert [s.visitas for s in serie] == [1, 0, 0, 1]


def test_semana_agrupa_a_partir_da_segunda_feira():
    visitas = [
        Visita(marco=datetime(2026, 10, 19, 9, tzinfo=FUSO_HORARIO)),  # segunda
        Visita(marco=datetime(2026, 10, 23, 18, tzinfo=FUSO_HORARIO)),  # sexta
    ]

    serie = dom.semanas(visitas)

    assert len(serie) == 1 and serie[0].visitas == 2
    assert serie[0].rotulo == "19/10"


def test_taxa_da_semana_e_ponderada_pelos_dias():
    visitas = [
        Visita(marco=AGORA, depois=1.0, dias=15),
        Visita(marco=AGORA, depois=5.0, dias=1),
    ]

    serie = dom.semanas(visitas)

    assert round(serie[0].disparos_por_dia, 3) == round((15 + 5) / 16, 3)


def test_serie_vazia_sem_visita_nenhuma():
    assert dom.semanas([]) == []


# ---------- antes × depois geral ----------


def test_antes_depois_geral_resume_a_base_comparavel():
    visitas = [
        Visita(conta="1", antes=2.0, depois=1.0),
        Visita(conta="2", antes=1.0, depois=0.0),
    ]

    geral = dom.antes_depois_geral(_lojas(visitas))

    assert geral.antes_por_dia == 1.5
    assert geral.depois_por_dia == 0.5
    assert geral.melhorou is True
    assert geral.lojas == 2


def test_antes_depois_sem_base_e_none_e_nao_duas_barras_zeradas():
    """Duas barras em zero leriam como "o técnico não conseguiu nada"."""
    assert dom.antes_depois_geral([]) is None
