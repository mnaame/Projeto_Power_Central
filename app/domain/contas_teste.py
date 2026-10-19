"""Contas em teste: ler a lista do Super Nosso e casar filial → conta.

Camada pura, sem rede e sem banco.

**O que está em jogo.** Colocar uma conta "em teste" faz a central parar
de tratar a falha de arme dela. Casar a filial errada aqui é alarme
suprimido na loja errada, e ninguém descobre pelo sistema — descobre
pelo arrombamento. Por isso este módulo prefere, em toda decisão
duvidosa, **não casar**: filial sem conta vira "não encontrada", filial
com duas contas vira "ambígua", e as duas listas vão para a tela em vez
de virarem um palpite.

**De onde vem a lista.** O Super Nosso manda uma mensagem por semana,
escrita por gente, com os números das filiais que não vão armar:

    420 SN. FLEMING
    688 SN. CASTELO
    530 AP. VENDA NOVA

O nome que vem na mensagem é abreviado e não bate com o cadastro
("SN. FLEMING" x "SUPER NOSSO (FLEMING FILIAL 420)"). Quem casa é o
**número da filial**, que aparece nos dois lados — e só ele.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Sequence

# Dois a quatro dígitos: é o tamanho de um número de filial. Mais que
# isso é CNPJ, telefone ou CEP que vieram junto no texto colado.
_RE_FILIAL = re.compile(r"\b\d{2,4}\b")

# "FILIAL 688", "FILIAL688", "FILIAL: 688"
_RE_FILIAL_NO_NOME = re.compile(r"FILIAL\s*:?\s*(\d{2,4})\b")

DURACAO_PADRAO_DIAS = 7


def normalizar(texto: str) -> str:
    sem_acento = "".join(
        c
        for c in unicodedata.normalize("NFD", (texto or "").upper())
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(sem_acento.split())


def extrair_filiais(mensagem: str) -> list[str]:
    """Números de filial do texto colado, na ordem, sem repetir.

    A ordem é preservada para a tela sair na mesma sequência da mensagem
    — conferir duas listas na mesma ordem é o que torna a revisão
    possível."""
    vistos: list[str] = []
    for achado in _RE_FILIAL.findall(mensagem or ""):
        numero = achado.lstrip("0") or achado
        if numero not in vistos:
            vistos.append(numero)
    return vistos


def filiais_do_nome(nome: str) -> set[str]:
    """Números de filial que aparecem no nome da conta.

    Procura primeiro a palavra "FILIAL" seguida do número, que é a forma
    do cadastro. Só quando ela não existe é que qualquer número solto no
    nome vale — e essa flexibilidade é o que exige o desempate por
    ambiguidade lá na frente."""
    normalizado = normalizar(nome)
    explicitos = {n.lstrip("0") or n for n in _RE_FILIAL_NO_NOME.findall(normalizado)}
    if explicitos:
        return explicitos
    return {n.lstrip("0") or n for n in _RE_FILIAL.findall(normalizado)}


@dataclass(frozen=True)
class ContaAlvo:
    """Uma conta do cadastro que pode receber o estado de teste."""

    cue_iid: str
    numero: str
    nome: str


@dataclass(frozen=True)
class Casamento:
    """O resultado de procurar uma filial no cadastro."""

    filial: str
    conta: ContaAlvo | None = None
    candidatas: tuple[ContaAlvo, ...] = ()

    @property
    def encontrada(self) -> bool:
        return self.conta is not None

    @property
    def ambigua(self) -> bool:
        return self.conta is None and len(self.candidatas) > 1


def casar_filiais(
    filiais: Sequence[str], contas: Iterable[ContaAlvo]
) -> list[Casamento]:
    """Casa cada filial com UMA conta, ou declara o problema.

    Três desfechos, e os três aparecem na tela:

    - uma conta → casada;
    - nenhuma → não encontrada (pode ser filial nova, pode ser número
      digitado errado; em qualquer caso não há o que adivinhar);
    - mais de uma → **ambígua**, e ninguém é escolhido. Escolher "a
      primeira" aqui seria colocar em teste uma loja que talvez vá armar
      hoje à noite.
    """
    indice: dict[str, list[ContaAlvo]] = {}
    for conta in contas:
        for numero in filiais_do_nome(conta.nome):
            indice.setdefault(numero, []).append(conta)

    resultado = []
    for filial in filiais:
        candidatas = indice.get(filial, [])
        if len(candidatas) == 1:
            resultado.append(Casamento(filial=filial, conta=candidatas[0]))
        else:
            resultado.append(
                Casamento(filial=filial, candidatas=tuple(candidatas))
            )
    return resultado


def janela(inicio: datetime, dias: int) -> tuple[datetime, datetime]:
    """Início e fim do teste.

    A janela é o que torna este módulo seguro: ela expira sozinha, e por
    isso não existe (nem precisa existir) um passo de remover. Duração
    menor que um dia é recusada — seria um teste que não cobre nem a
    noite para a qual foi pedido."""
    if dias < 1:
        raise ValueError("A duração do teste precisa ser de pelo menos 1 dia.")
    return inicio, inicio + timedelta(days=dias)
