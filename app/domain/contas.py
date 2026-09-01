"""Contas e partições da PowerCentral. Camada pura — sem I/O.

Uma conta pode ser dividida em **partições** (setores independentes do
mesmo local: loja, tesouraria, depósito). No portal cada partição é uma
linha própria em `CuentaByDealer`, com o mesmo `cue_ncuenta` e o seu
próprio `cue_iid` — e é o `cue_iid` que o zoneamento e o export usam. Por
isso escolher a partição é escolher qual `cue_iid` consultar.

O resto do sistema (relatórios, BI, técnico) só olha `cue_nparticion = 0`
e por isso nunca precisou disto; o bot é o primeiro a precisar, porque o
técnico em campo trabalha no setor, não na conta inteira.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

# Partição 0 é a conta "inteira" no portal — não é um setor, é o registro
# principal. Fica na lista de escolha mesmo assim: só quem conhece o local
# sabe se o evento procurado está nela ou num setor.
PARTICAO_PRINCIPAL = 0


@dataclass(frozen=True)
class Conta:
    numero: str  # normalizado (sem zeros à esquerda)
    particao: int
    cue_iid: str
    nome: str

    @property
    def identificacao(self) -> str:
        """Como o técnico se refere a esta conta num comando: `95` ou
        `95/2`. É o mesmo texto que ele copia da lista de partições."""
        if self.particao == PARTICAO_PRINCIPAL:
            return self.numero
        return f"{self.numero}/{self.particao}"

    @property
    def rotulo(self) -> str:
        """Como a conta aparece nas listagens."""
        return f"{self.identificacao} — {self.nome}"

    @property
    def sufixo_arquivo(self) -> str:
        """Partição entra no nome do arquivo: sem isso, duas partições da
        mesma conta gerariam arquivos de nome igual no mesmo chat."""
        return "" if self.particao == PARTICAO_PRINCIPAL else f" P{self.particao}"


def _texto(valor: object) -> str:
    return str(valor).strip() if valor is not None else ""


def normalizar_numero(numero: str) -> str:
    """Mesma normalização de conta do resto do sistema."""
    return _texto(numero).lstrip("0") or "0"


def _particao(valor: object) -> int:
    """Defensivo: o campo pode vir int, str ou ausente. Qualquer coisa
    que não seja número vira 0 (a conta principal) em vez de quebrar —
    pior caso o técnico vê uma opção a mais, nunca um erro."""
    try:
        return int(_texto(valor) or 0)
    except ValueError:
        return PARTICAO_PRINCIPAL


def contas_da_resposta(linhas: Sequence[Mapping[str, object]]) -> list[Conta]:
    """Converte as linhas cruas de `listar_todas_contas` em `Conta`.
    Linha sem `cue_iid` é descartada: sem ele não dá para consultar nada."""
    contas = []
    for linha in linhas:
        cue_iid = linha.get("cue_iid") or linha.get("Id")
        if cue_iid is None:
            continue
        contas.append(
            Conta(
                numero=normalizar_numero(_texto(linha.get("cue_ncuenta"))),
                particao=_particao(linha.get("cue_nparticion")),
                cue_iid=str(cue_iid),
                nome=_texto(linha.get("cue_cnombre")),
            )
        )
    return contas


def agrupar_por_numero(contas: Sequence[Conta]) -> dict[str, list[Conta]]:
    """Número da conta -> suas partições, em ordem de partição. Uma conta
    sem partições vira uma lista de um item só."""
    agrupado: dict[str, list[Conta]] = {}
    for conta in contas:
        agrupado.setdefault(conta.numero, []).append(conta)
    for particoes in agrupado.values():
        particoes.sort(key=lambda c: c.particao)
    return agrupado


def tem_particoes(particoes: Sequence[Conta]) -> bool:
    return len(particoes) > 1


def escolher_particao(particoes: Sequence[Conta], numero_particao: int) -> Conta | None:
    for conta in particoes:
        if conta.particao == numero_particao:
            return conta
    return None
