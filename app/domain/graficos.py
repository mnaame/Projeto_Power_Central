"""Geometria de gráfico — puro, sem Flask e sem SVG escrito à mão no
template.

Os gráficos deste projeto são SVG montado no servidor: sem biblioteca de
chart, sem JSON de dados vazando para a página. O template desenha; as
contas (escala, eixo, posição de cada barra) ficam aqui, onde dá para
testar que a barra de 0,83 é mesmo o dobro da de 0,41.

**Por que não `rx` nas barras.** A especificação de marca pede ponta
arredondada *em cima* e quadrada na base — `rx` arredonda os quatro
cantos, e barra com base redonda descola do eixo. Daí `caminho_coluna`
devolver um `d` com dois arcos só.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

# Passos "bonitos" para o topo do eixo. Um eixo que termina em 0,83 pede
# que o leitor divida 0,83 por 4 de cabeça; terminando em 1,0 ele lê a
# metade de olho.
_PASSOS_BONITOS = (1.0, 2.0, 2.5, 5.0, 10.0)

# Espessura máxima da barra. Barra que preenche a faixa inteira vira
# bloco; o resto da faixa é respiro, não desperdício.
LARGURA_MAXIMA_COLUNA = 24.0
RAIO_PONTA = 4.0


def passo_bonito(bruto: float) -> float:
    """Arredonda um passo de eixo para cima, para 1/2/2,5/5/10 × 10^k."""
    if bruto <= 0:
        return 1.0
    expoente = 0
    escala = float(bruto)
    while escala >= 10.0:
        escala /= 10.0
        expoente += 1
    while escala < 1.0:
        escala *= 10.0
        expoente -= 1
    for candidato in _PASSOS_BONITOS:
        if escala <= candidato + 1e-9:
            return candidato * (10.0**expoente)
    return 10.0 * (10.0**expoente)


@dataclass(frozen=True)
class Eixo:
    maximo: float
    passo: float
    valores: tuple[float, ...]

    @property
    def casas(self) -> int:
        """Casas decimais que o PASSO exige — não um número fixo.

        Com passo 0,25 o eixo precisa de duas casas; com 0,1, uma. Fixar
        em duas escreveria "0,10 / 0,20 / 0,30", que é ruído, e fixar em
        uma transformaria 0,25 em 0,3 — um eixo que mente."""
        if self.passo >= 1:
            return 0
        return 1 if abs(self.passo * 10 - round(self.passo * 10)) < 1e-9 else 2


# Quantas marcas tentar. Um eixo que vai até 2,00 para um valor máximo de
# 1,20 joga fora 40% da altura do gráfico e achata todas as barras — foi
# o que aconteceu na primeira renderização. Testando mais de uma divisão
# e ficando com o teto mais justo, o mesmo 1,20 fecha em 1,25.
_DIVISOES_CANDIDATAS = (4, 5, 3)


def eixo(maximo_bruto: float, *, divisoes: int | None = None) -> Eixo:
    """Topo e marcas do eixo de valor, sempre em número redondo e o mais
    justo possível.

    Máximo zero (nenhum disparo no período) ainda devolve um eixo
    utilizável: sem isso o gráfico sairia sem eixo nenhum e o "zero" viria
    como gráfico quebrado, não como resultado."""
    bruto = max(float(maximo_bruto or 0.0), 0.0)
    candidatas = (max(int(divisoes), 1),) if divisoes else _DIVISOES_CANDIDATAS

    if bruto <= 0:
        n = candidatas[0]
        return Eixo(maximo=float(n), passo=1.0, valores=tuple(float(i) for i in range(n + 1)))

    melhor: tuple[float, float, int] | None = None
    for n in candidatas:
        passo = passo_bonito(bruto / n)
        maximo = passo * n
        if melhor is None or maximo < melhor[0] - 1e-9:
            melhor = (maximo, passo, n)

    maximo, passo, n = melhor  # type: ignore[misc]
    return Eixo(maximo=maximo, passo=passo, valores=tuple(passo * i for i in range(n + 1)))


def caminho_coluna(x: float, y: float, largura: float, altura: float) -> str:
    """`d` de uma coluna com ponta arredondada e base quadrada."""
    if altura <= 0 or largura <= 0:
        return ""
    raio = min(RAIO_PONTA, largura / 2.0, altura)
    base = y + altura
    return (
        f"M {x:.1f} {base:.1f} "
        f"V {y + raio:.1f} "
        f"Q {x:.1f} {y:.1f} {x + raio:.1f} {y:.1f} "
        f"H {x + largura - raio:.1f} "
        f"Q {x + largura:.1f} {y:.1f} {x + largura:.1f} {y + raio:.1f} "
        f"V {base:.1f} Z"
    )


@dataclass(frozen=True)
class Coluna:
    rotulo: str
    valor: float
    classe: str
    caminho: str
    centro_x: float
    topo_y: float
    banda_x: float
    banda_largura: float
    mostrar_rotulo: bool
    detalhe: str = ""


@dataclass
class Grafico:
    largura: int
    altura: int
    base_y: float
    topo_y: float
    eixo_x: float
    colunas: list[Coluna] = field(default_factory=list)
    marcas: list[dict] = field(default_factory=list)


def montar_colunas(
    itens: Sequence[tuple[str, float, str, str]],
    *,
    largura: int,
    altura: int,
    margem_esquerda: float = 42.0,
    margem_direita: float = 12.0,
    margem_topo: float = 16.0,
    margem_base: float = 28.0,
    casas: int = 2,
    maximo_rotulos: int = 10,
) -> Grafico:
    """`itens` são `(rótulo, valor, classe, detalhe)`.

    `classe` é a função da cor (neutro / melhora / piora), não a série:
    cor de status não vira "série 3" neste projeto.

    `maximo_rotulos` existe porque o eixo de datas é o primeiro a quebrar:
    com 30 semanas os rótulos se encavalam e viram borrão. Passando do
    limite, mostra-se um a cada N — as barras continuam todas lá, e o
    hover diz a data de qualquer uma."""
    grafico = Grafico(
        largura=largura,
        altura=altura,
        base_y=altura - margem_base,
        topo_y=margem_topo,
        eixo_x=margem_esquerda,
    )
    if not itens:
        return grafico

    escala = eixo(max((valor for _, valor, _, _ in itens), default=0.0))
    altura_util = grafico.base_y - margem_topo
    largura_util = largura - margem_esquerda - margem_direita
    faixa = largura_util / len(itens)
    largura_coluna = min(faixa * 0.55, LARGURA_MAXIMA_COLUNA)
    passo_rotulo = max(1, -(-len(itens) // max(maximo_rotulos, 1)))

    for valor in escala.valores:
        y = grafico.base_y - (valor / escala.maximo) * altura_util
        grafico.marcas.append(
            {
                "y": round(y, 1),
                "valor": valor,
                "rotulo": formatar_numero(valor, escala.casas if valor else 0),
            }
        )

    for indice, (rotulo, valor, classe, detalhe) in enumerate(itens):
        centro = margem_esquerda + faixa * (indice + 0.5)
        alto = (max(float(valor), 0.0) / escala.maximo) * altura_util
        topo = grafico.base_y - alto
        grafico.colunas.append(
            Coluna(
                rotulo=rotulo,
                valor=float(valor),
                classe=classe,
                caminho=caminho_coluna(centro - largura_coluna / 2, topo, largura_coluna, alto),
                centro_x=round(centro, 1),
                topo_y=round(topo, 1),
                banda_x=round(margem_esquerda + faixa * indice, 1),
                banda_largura=round(faixa, 1),
                mostrar_rotulo=(indice % passo_rotulo == 0),
                detalhe=detalhe,
            )
        )
    return grafico


def formatar_numero(valor: float, casas: int = 2) -> str:
    """Vírgula decimal — a tela é lida em português."""
    return f"{valor:.{casas}f}".replace(".", ",")
