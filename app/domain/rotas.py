"""Catálogo de visita preventiva — agrupa os clientes base por bairro.

Camada pura, sem rede.

**Por que bairro e não distância.** A primeira versão agrupava por raio em
quilômetros (haversine + clusters por limiar). Funcionava, e mesmo assim
foi descartada: ela dependia de o cadastro ter latitude e longitude, que
é justamente o campo que falta, e respondia uma pergunta que a operação
não faz. Quem monta a agenda pensa "quem eu tenho no Padre Eustáquio?",
não "quem está a 1,5 km deste ponto". Bairro é a unidade que a equipe já
usa para falar de região, vem escrito no endereço que o cadastro tem, e
não precisa de coordenada nenhuma.

**Bairro sempre com cidade.** "Centro" existe em Belo Horizonte, em
Contagem e em Betim. Agrupar só pelo nome do bairro juntaria clientes a
trinta quilômetros um do outro numa "mesma região", que é o erro mais
caro que este módulo poderia cometer.

**Quem não tem bairro não some.** Cai numa região "(sem bairro) —
Cidade", que fica no fim da lista e é a fila de trabalho do cadastro.
Some seria pior: ninguém procura o que não aparece.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Sequence

from app.domain import endereco as end

# Casamento por nome é a reserva de quando não há de-para. O corte é alto
# de propósito: ligar o cliente errado a um endereço manda o técnico para
# a região de outra pessoa.
CORTE_NOME_PADRAO = 0.88

FONTE_AUVO = "Auvo"
FONTE_AUVO_PLANILHA = "Auvo (planilha)"
FONTE_POWER = "PowerCentral"
FONTE_POWER_PLANILHA = "PowerCentral (planilha)"
FONTE_MANUAL = "corrigido à mão"

# Clientes que não são clientes.
PADROES_INTERNOS = ("NOVO MILLENIUM", "NOVO MILLENNIUM", "CONTA TESTE")

ROTULO_SEM_BAIRRO = "(sem bairro)"
ROTULO_SEM_REGIAO = "(sem endereço)"


@dataclass(frozen=True)
class ClienteBase:
    """Um cliente base já com a região resolvida."""

    conta: str
    nome: str
    bairro: str = ""
    cidade: str = ""
    fonte: str = ""
    # Para o mapa. Nulo = cliente sem coordenada conhecida; ele continua
    # no catálogo e na lista, só não aparece no mapa.
    lat: float | None = None
    lon: float | None = None

    @property
    def tem_coordenada(self) -> bool:
        return self.lat is not None and self.lon is not None

    @property
    def chave_regiao(self) -> str:
        return end.chave_regiao(self.bairro, self.cidade)

    @property
    def rotulo_regiao(self) -> str:
        if self.bairro:
            return end.rotulo_regiao(self.bairro, self.cidade)
        if self.cidade:
            return f"{ROTULO_SEM_BAIRRO} — {end.titulo(self.cidade)}"
        return ROTULO_SEM_REGIAO


@dataclass
class Regiao:
    """Um bairro (com a cidade) e os clientes que estão nele."""

    rotulo: str
    chave: str
    clientes: list[ClienteBase] = field(default_factory=list)

    @property
    def tamanho(self) -> int:
        return len(self.clientes)

    @property
    def tem_bairro(self) -> bool:
        return bool(self.clientes and self.clientes[0].bairro)

    @property
    def cidade(self) -> str:
        return end.titulo(self.clientes[0].cidade) if self.clientes else ""


def normalizar(texto: str) -> str:
    """Maiúsculas, sem acento e sem espaço sobrando — mesma régua usada
    para comparar nome de cliente no resto do sistema."""
    sem_acento = "".join(
        c
        for c in unicodedata.normalize("NFD", (texto or "").upper())
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(sem_acento.split())


def e_interno(nome: str) -> bool:
    normalizado = normalizar(nome)
    return any(padrao in normalizado for padrao in PADROES_INTERNOS)


def semelhanca(a: str, b: str) -> float:
    return SequenceMatcher(None, normalizar(a), normalizar(b)).ratio()


def melhor_nome(
    nome: str, candidatos: Sequence[str], *, corte: float = CORTE_NOME_PADRAO
) -> str:
    """Nome mais parecido acima do corte, ou vazio. Empate devolve o
    primeiro — determinístico, nunca arbitrário."""
    melhor, melhor_score = "", 0.0
    for candidato in candidatos:
        score = semelhanca(nome, candidato)
        if score > melhor_score:
            melhor, melhor_score = candidato, score
    return melhor if melhor_score >= corte else ""


def agrupar_por_regiao(clientes: Sequence[ClienteBase]) -> list[Regiao]:
    """Agrupa por bairro+cidade.

    A ordem da saída é a ordem em que a operação decide o que fazer: as
    regiões com mais clientes primeiro, porque são as que rendem mais
    numa saída só; as sem bairro por último, porque não são uma visita,
    são uma pendência de cadastro. Empate sai em ordem alfabética do
    rótulo, e os clientes de cada região saem por número de conta — rodar
    duas vezes com os mesmos dados tem que dar exatamente a mesma
    resposta, senão a equipe não consegue conferir nada."""
    grupos: dict[str, Regiao] = {}
    for cliente in clientes:
        chave = cliente.chave_regiao
        regiao = grupos.get(chave)
        if regiao is None:
            regiao = Regiao(rotulo=cliente.rotulo_regiao, chave=chave)
            grupos[chave] = regiao
        regiao.clientes.append(cliente)

    for regiao in grupos.values():
        regiao.clientes.sort(key=lambda c: c.conta)

    return sorted(
        grupos.values(),
        key=lambda r: (not r.tem_bairro, -r.tamanho, r.rotulo),
    )
