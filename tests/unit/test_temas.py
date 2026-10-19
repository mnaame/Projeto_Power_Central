"""Temas: as mesmas variáveis em todos, e contraste legível nos três.

Um tema não é decoração: é a tela inteira. Se um tema esquece uma
variável, o componente que a usa fica com a cor do tema anterior — texto
branco sobre fundo branco, borda invisível, chip ilegível — e isso só
aparece quando alguém abre justamente aquela tela.
"""

import re
from pathlib import Path

TOKENS = Path(__file__).resolve().parents[2] / "app/web/static/css/tokens.css"

TEMAS = ("light", "dark", "preto", "sepia")


def _bloco(nome: str) -> dict[str, str]:
    """As variáveis declaradas no bloco `:root[data-theme="<nome>"]`."""
    css = TOKENS.read_text(encoding="utf-8")
    if nome == "light":
        # O claro é o `:root` base, que também declara as variáveis
        # estruturais (espaçamento, fonte) — aqui só interessam as cores.
        inicio = css.index(":root,\n:root[data-theme=\"light\"]")
    else:
        inicio = css.index(f':root[data-theme="{nome}"]')
    corpo = css[css.index("{", inicio) + 1 : css.index("}", inicio)]
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", corpo))


def _cores_do_claro() -> set[str]:
    """As variáveis de COR do tema claro — o conjunto que todo tema
    precisa cobrir. O `:root` base tem muito mais (espaçamento, raio,
    fonte), e essas não mudam por tema."""
    css = TOKENS.read_text(encoding="utf-8")
    todas = set(_bloco("light"))
    # O `:root` de cima também declara cores de status, que valem para o
    # claro e são sobrescritas pelos escuros.
    primeiro = css[css.index(":root {") : css.index("}", css.index(":root {"))]
    todas |= {
        nome
        for nome, _ in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", primeiro)
        if nome.startswith("--color-status")
    }
    return {n for n in todas if n.startswith("--color-")}


def _luminancia(cor: str) -> float:
    cor = cor.strip().lstrip("#")
    def canal(valor: str) -> float:
        v = int(valor, 16) / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = canal(cor[0:2]), canal(cor[2:4]), canal(cor[4:6])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(frente: str, fundo: str) -> float:
    a, b = _luminancia(frente), _luminancia(fundo)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


# ---------- cobertura das variáveis ----------


def test_temas_escuros_redefinem_todas_as_cores_do_claro():
    """Variável esquecida = componente com a cor do tema anterior. Texto
    escuro sobre fundo preto não dá erro em lugar nenhum: só fica
    ilegível na tela que ninguém abriu ainda."""
    esperadas = _cores_do_claro()

    for tema in ("preto", "sepia"):
        faltando = esperadas - set(_bloco(tema))
        assert not faltando, f"{tema} não define: {sorted(faltando)}"


def test_os_tres_temas_do_seletor_existem():
    for tema in ("light", "preto", "sepia"):
        assert _bloco(tema), f"tema {tema} não encontrado em tokens.css"


# ---------- contraste ----------


PARES = [
    ("--color-text-primary", "--color-bg"),
    ("--color-text-primary", "--color-surface"),
    ("--color-text-secondary", "--color-surface"),
    ("--color-text-muted", "--color-surface"),
    ("--color-accent", "--color-bg"),
    ("--color-accent", "--color-accent-soft"),
    ("--color-status-critical", "--color-status-critical-bg"),
    ("--color-status-ok", "--color-status-ok-bg"),
]


def test_contraste_minimo_aa_nos_temas_novos():
    """AA é 4,5:1 para texto normal. O sépia é de baixo contraste de
    propósito — "sem branco estourando" —, mas baixo contraste não pode
    virar ilegível."""
    for tema in ("preto", "sepia"):
        cores = _bloco(tema)
        for frente, fundo in PARES:
            razao = contraste(cores[frente], cores[fundo])
            assert razao >= 4.5, (
                f"{tema}: {frente} sobre {fundo} = {razao:.2f}:1 (mínimo 4,5)"
            )


def test_preto_e_preto_de_verdade():
    """AMOLED: num painel OLED o #000 é pixel desligado. Um cinza escuro
    serviria, mas não é o que foi pedido nem o que economiza bateria."""
    assert _bloco("preto")["--color-bg"].strip() == "#000000"


def test_sepia_e_quente():
    """Sépia com fundo neutro vira só um cinza escuro. O canal vermelho
    tem que ser maior que o azul."""
    fundo = _bloco("sepia")["--color-bg"].strip().lstrip("#")
    vermelho, azul = int(fundo[0:2], 16), int(fundo[4:6], 16)

    assert vermelho > azul
