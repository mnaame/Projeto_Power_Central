"""Lojas sem arme: ler a lista do Super Nosso e casar filial → conta.

Camada pura, sem rede e sem banco.

**O que está em jogo.** Desligar o aviso de arme de uma conta faz a
central parar de avisar que aquela loja não armou. Casar a filial errada
aqui é uma loja sem essa supervisão, e ninguém descobre pelo sistema.

(O disparo continua chegando — é a diferença entre este mecanismo e
colocar a conta em teste, que calava tudo, inclusive invasão.)

Por isso este módulo prefere, em toda decisão duvidosa, **não casar**:
filial sem conta vira "não encontrada", filial com duas contas vira
"ambígua", e as duas listas vão para a tela em vez de virarem um
palpite.

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

# Contas que NUNCA são desligadas, por mais que o número bata.
#
# A tesouraria é conta separada da loja no cadastro ("SUPER NOSSO CASTELO
# LOJA" e "SUPER NOSSO CASTELO TESOURARIA"), e ela não participa do
# serviço noturno: arma normalmente, e o aviso dela tem que continuar
# funcionando.
#
# Hoje, na base real, nenhuma tesouraria tem número de filial no nome —
# então, por sorte, o casamento por número nunca a alcançaria. Mas isso é
# uma propriedade do cadastro de hoje, não uma garantia: basta alguém
# renomear a conta para "CASTELO TESOURARIA FILIAL 688" e a sorte acaba.
# A regra fica no código, onde ela não depende de ninguém lembrar.
PADROES_NUNCA_EM_TESTE = ("TESOURARIA",)


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


def nunca_desligar(nome: str) -> bool:
    """Conta que não pode ser desligada nem se o número bater."""
    normalizado = normalizar(nome)
    return any(padrao in normalizado for padrao in PADROES_NUNCA_EM_TESTE)


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


@dataclass(frozen=True)
class Diferenca:
    """O que a lista desta semana muda em relação ao que está desligado.

    São **dois sentidos**, e é isso que o mecanismo anterior dispensava:
    lá a janela expirava sozinha, aqui o religar é um passo que alguém
    precisa dar. Uma conta que saiu da lista e não for religada fica sem
    o aviso indefinidamente."""

    desligar: tuple[ContaAlvo, ...] = ()
    religar: tuple[str, ...] = ()        # cue_iid das que saíram da lista
    ja_desligadas: tuple[ContaAlvo, ...] = ()


def diferenca_da_semana(
    casadas: Sequence[ContaAlvo], desligadas_agora: Iterable[str]
) -> Diferenca:
    """Compara a lista nova com o que já está desligado.

    - Está na lista e ligada → **desligar**.
    - Está desligada e saiu da lista → **religar**.
    - Está na lista e já desligada → não mexe. Reenviar o desligamento
      regravaria o ledger com `nnyc_original = 1`, ou seja, perderia para
      sempre o valor que a conta tinha antes. É o erro mais caro possível
      aqui, e por isso a conta já desligada é tratada à parte."""
    desligadas = {str(i) for i in desligadas_agora}
    pedidas = {c.cue_iid for c in casadas}

    return Diferenca(
        desligar=tuple(c for c in casadas if c.cue_iid not in desligadas),
        religar=tuple(sorted(desligadas - pedidas)),
        ja_desligadas=tuple(c for c in casadas if c.cue_iid in desligadas),
    )
