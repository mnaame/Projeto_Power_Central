import string

from app.domain.cofre import (
    FORTE,
    FRACA,
    MEDIA,
    MUITO_FORTE,
    forca_senha,
    gerar_senha,
)


# ---------- gerar_senha ----------


def test_gerar_senha_tamanho_padrao():
    assert len(gerar_senha()) == 20


def test_gerar_senha_respeita_tamanho_pedido():
    assert len(gerar_senha(tamanho=32)) == 32


def test_gerar_senha_nunca_abaixo_do_minimo():
    assert len(gerar_senha(tamanho=1)) == 8


def test_gerar_senha_contem_todas_as_categorias():
    senha = gerar_senha(tamanho=20)
    assert any(c in string.ascii_lowercase for c in senha)
    assert any(c in string.ascii_uppercase for c in senha)
    assert any(c in string.digits for c in senha)
    assert any(not c.isalnum() for c in senha)


def test_gerar_senha_exclui_ambiguos_por_padrao():
    for _ in range(50):
        senha = gerar_senha(tamanho=20)
        assert not any(c in "Il1O0" for c in senha)


def test_gerar_senha_duas_chamadas_sao_diferentes():
    assert gerar_senha() != gerar_senha()


# ---------- forca_senha ----------


def test_forca_senha_vazia_ou_curta_e_fraca():
    assert forca_senha("") == FRACA
    assert forca_senha("Ab1!") == FRACA


def test_forca_senha_so_minuscula_longa_ainda_fraca():
    assert forca_senha("abcdefghijkl") == FRACA


def test_forca_senha_media_com_duas_categorias_e_tamanho():
    assert forca_senha("abcdefghijkl1") == MEDIA


def test_forca_senha_forte_com_variedade_e_tamanho():
    assert forca_senha("Abcdefghijkl1") == FORTE


def test_forca_senha_muito_forte_gerada():
    assert forca_senha(gerar_senha(tamanho=20)) == MUITO_FORTE
