from app.domain.diffing import detectar_mudanca


def test_sem_mudanca_quando_conjuntos_iguais():
    resultado = detectar_mudanca(["1001", "1002"], ["1002", "1001"])
    assert resultado.mudou is False
    assert resultado.tipo is None


def test_sem_mudanca_quando_ambos_vazios():
    resultado = detectar_mudanca([], [])
    assert resultado.mudou is False
    assert resultado.tipo is None


def test_entrada_quando_conta_nova_aparece():
    resultado = detectar_mudanca(["1001"], ["1001", "1002"])
    assert resultado.mudou is True
    assert resultado.tipo == "entrada"
    assert resultado.contas_adicionadas == ["1002"]
    assert resultado.contas_removidas == []


def test_saida_quando_uma_conta_normaliza_mas_outras_continuam():
    resultado = detectar_mudanca(["1001", "1002"], ["1001"])
    assert resultado.tipo == "saida"
    assert resultado.contas_removidas == ["1002"]
    assert resultado.contas_adicionadas == []


def test_normalizacao_quando_lista_fica_vazia():
    resultado = detectar_mudanca(["1001", "1002"], [])
    assert resultado.tipo == "normalizacao"
    assert resultado.contas_adicionadas == []
    assert resultado.contas_removidas == ["1001", "1002"]


def test_entrada_tem_prioridade_quando_ha_entrada_e_saida_simultaneas():
    resultado = detectar_mudanca(["1001"], ["1002"])
    assert resultado.tipo == "entrada"
    assert resultado.contas_adicionadas == ["1002"]
    assert resultado.contas_removidas == ["1001"]
