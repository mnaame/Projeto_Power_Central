"""Contas e partições da PowerCentral. Camada pura — sem I/O.

Como partição funciona de verdade no portal (validado em produção com
`scripts/debug_particoes.py`, contra a base real):

- **cada partição é uma conta própria**, com o seu `cue_ncuenta` e o seu
  `cue_iid`. A tesouraria da VILLEFORT TROPICAL (conta 0004) é a conta
  0005, "VILLEFORT ATACADISTA TROPICAL - TESOURARIA";
- `cue_nparticion` **não é o número da partição** — é o `cue_iid` da conta
  MÃE (0 quando a conta não é partição de ninguém). Por isso o filtro
  `cue_nparticion = 0` do resto do sistema devolve só as contas
  principais;
- o vínculo legível com a mãe vem em `madre_ncuenta` / `madre_cnombre`.

Consequência prática: o técnico não precisa de sintaxe especial — ele pede
`/zona 5` e pronto, porque 5 é uma conta de verdade. O que o bot faz é,
quando pedem a conta MÃE, listar as partições dela para escolher, em vez
de assumir que a pergunta era sobre o local inteiro.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class Conta:
    numero: str  # normalizado (sem zeros à esquerda)
    cue_iid: str
    nome: str
    # Número normalizado da conta mãe; vazio quando não é partição.
    conta_mae: str = ""

    @property
    def e_particao(self) -> bool:
        return bool(self.conta_mae)

    @property
    def identificacao(self) -> str:
        """Como o técnico se refere a esta conta num comando. É só o
        número: partição é conta de verdade, não precisa de sufixo."""
        return self.numero

    @property
    def rotulo(self) -> str:
        return f"{self.numero} — {self.nome}"


def _texto(valor: object) -> str:
    # Os campos de conta vêm preenchidos com espaços à direita no portal.
    return str(valor).strip() if valor is not None else ""


def normalizar_numero(numero: str) -> str:
    """Mesma normalização de conta do resto do sistema."""
    return _texto(numero).lstrip("0") or "0"


def _e_particao(linha: Mapping[str, object]) -> bool:
    """`cue_nparticion` guarda o `cue_iid` da mãe — qualquer valor não-zero
    significa "sou partição de alguém". É o mesmo critério do filtro que o
    resto do sistema usa para pegar só as principais."""
    bruto = _texto(linha.get("cue_nparticion"))
    return bool(bruto) and bruto not in {"0", "0.0"}


def contas_da_resposta(linhas: Sequence[Mapping[str, object]]) -> list[Conta]:
    """Converte as linhas cruas de `listar_todas_contas` em `Conta`.
    Linha sem `cue_iid` é descartada: sem ele não dá para consultar nada."""
    contas = []
    for linha in linhas:
        cue_iid = linha.get("cue_iid") or linha.get("Id")
        if cue_iid is None:
            continue
        numero = normalizar_numero(_texto(linha.get("cue_ncuenta")))
        mae = normalizar_numero(_texto(linha.get("madre_ncuenta")))
        # Só vale como mãe se a linha É partição e a mãe não é ela mesma.
        conta_mae = mae if _e_particao(linha) and mae != numero else ""
        contas.append(
            Conta(
                numero=numero,
                cue_iid=str(cue_iid),
                nome=_texto(linha.get("cue_cnombre")),
                conta_mae=conta_mae,
            )
        )
    return contas


def particoes_de(contas: Sequence[Conta], numero: str) -> list[Conta]:
    """Partições de uma conta, na ordem do número. Lista vazia quando a
    conta não tem partição (ou quando a própria conta É uma partição —
    partição de partição não existe na base)."""
    filhas = [c for c in contas if c.conta_mae == numero]
    return sorted(filhas, key=_ordem)


def familia(contas: Sequence[Conta], conta: Conta) -> list[Conta]:
    """A conta mãe seguida das partições dela — a lista que o técnico vê
    para escolher. Para uma conta sem partição, é só ela mesma."""
    filhas = particoes_de(contas, conta.numero)
    return [conta, *filhas] if filhas else [conta]


def _ordem(conta: Conta):
    try:
        return (0, int(conta.numero), conta.nome)
    except ValueError:
        return (1, 0, conta.nome)


def ordenar(contas: Sequence[Conta]) -> list[Conta]:
    """Por número — é como a operação enxerga a base."""
    return sorted(contas, key=_ordem)
