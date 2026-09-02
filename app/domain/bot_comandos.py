"""Comandos do bot do técnico no Telegram: parsing e resolução de conta.
Camada pura — sem I/O, sem Flask, sem Telegram.

Disciplina anti-erro do resto do sistema: nome ambíguo NUNCA vira um chute.
Quando o termo casa com mais de um cliente, devolve-se a lista para o
técnico escolher — mandar o zoneamento da loja errada é vazar o mapa de
segurança de um cliente para outro.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Mapping, Sequence

from app.domain import contas as dom_contas
from app.domain.contas import Conta

COMANDO_RELATORIO = "relatorio"
COMANDO_ZONA = "zona"
COMANDO_AJUDA = "ajuda"
COMANDO_CLIENTES = "clientes"
COMANDOS_CONHECIDOS = (
    COMANDO_RELATORIO,
    COMANDO_ZONA,
    COMANDO_AJUDA,
    COMANDO_CLIENTES,
)

# Quantos clientes listar quando o nome é ambíguo — a resposta tem que
# caber numa mensagem e continuar legível no celular.
MAX_SUGESTOES = 10

RESOLUCAO_OK = "ok"
RESOLUCAO_AMBIGUA = "ambigua"
RESOLUCAO_NAO_ENCONTRADA = "nao_encontrada"
# A conta pedida é a MÃE de outras (tesouraria, depósito): lista a
# família e pergunta, em vez de assumir que era sobre o local inteiro.
RESOLUCAO_PARTICOES = "particoes"


@dataclass(frozen=True)
class Comando:
    """`nome` vazio = não é comando (texto solto) ou comando desconhecido."""

    nome: str
    argumentos: tuple[str, ...]


@dataclass(frozen=True)
class Resolucao:
    status: str  # OK | AMBIGUA | PARTICOES | NAO_ENCONTRADA
    conta: Conta | None
    candidatas: tuple[Conta, ...]


def _sem_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


def normalizar(texto: str) -> str:
    return _sem_acentos(texto or "").strip().lower()


def normalizar_conta(numero: str) -> str:
    """Mesma normalização de conta do resto do sistema (sem zeros à
    esquerda) — `0095`, `95` e `095` são a mesma conta."""
    return (numero or "").strip().lstrip("0") or "0"


def interpretar(texto: str) -> Comando:
    """Parsing tolerante: aceita `/zona 95`, `/Zona 95` e `/zona@MeuBot 95`
    (o Telegram acrescenta o @bot quando o comando é dado em grupo)."""
    limpo = (texto or "").strip()
    if not limpo.startswith("/"):
        return Comando(nome="", argumentos=())

    partes = limpo.split()
    nome = partes[0][1:].split("@", 1)[0].lower()
    nome = normalizar(nome)
    if nome not in COMANDOS_CONHECIDOS:
        return Comando(nome="", argumentos=())
    return Comando(nome=nome, argumentos=tuple(partes[1:]))


def separar_conta_e_dias(argumentos: Sequence[str]) -> tuple[str, int | None]:
    """`/relatorio <conta> [dias]`. O último argumento só vira "dias" se
    for número E houver mais de um argumento — assim `/relatorio 9516`
    continua sendo a conta 9516, e `/relatorio AUTO MECANICA 15` vira
    ("AUTO MECANICA", 15)."""
    itens = [a for a in argumentos if a.strip()]
    if not itens:
        return "", None
    if len(itens) > 1 and itens[-1].isdigit():
        return " ".join(itens[:-1]), int(itens[-1])
    return " ".join(itens), None


def resolver_conta(termo: str, contas: Sequence[Conta]) -> Resolucao:
    """Aceita número (`5`, `0005`) ou parte do nome.

    Partição é conta de verdade, com número próprio — então `/zona 5` já
    resolve direto, sem sintaxe especial. O que exige pergunta é o
    contrário: pedir a conta MÃE de um local que tem setores separados.
    Aí o bot lista a família (mãe + partições) e deixa o técnico escolher,
    porque "o histórico da VILLEFORT TROPICAL" pode significar a loja ou a
    tesouraria — e entregar o setor errado é entregar a informação errada.
    """
    termo = (termo or "").strip()
    if not termo:
        return Resolucao(RESOLUCAO_NAO_ENCONTRADA, None, ())

    if termo.isdigit():
        alvo_numero = dom_contas.normalizar_numero(termo)
        encontradas = [c for c in contas if c.numero == alvo_numero]
    else:
        alvo = normalizar(termo)
        encontradas = [c for c in contas if alvo in normalizar(c.nome)]
        # Nome idêntico (não só contido) resolve a ambiguidade: "VILLEFORT
        # HM" não pode ficar preso porque existe "VILLEFORT HM DEPOSITO".
        exatas = [c for c in encontradas if normalizar(c.nome) == alvo]
        if len(exatas) == 1:
            encontradas = exatas

    if not encontradas:
        return Resolucao(RESOLUCAO_NAO_ENCONTRADA, None, ())
    if len(encontradas) > 1:
        return Resolucao(
            RESOLUCAO_AMBIGUA, None, tuple(dom_contas.ordenar(encontradas))
        )

    conta = encontradas[0]
    familia = dom_contas.familia(contas, conta)
    if len(familia) > 1:
        return Resolucao(RESOLUCAO_PARTICOES, None, tuple(familia))
    return Resolucao(RESOLUCAO_OK, conta, ())


def formatar_ambiguidade(candidatas: Sequence[Conta]) -> str:
    """Lista curta para o técnico repetir o comando com o número — o bot
    nunca escolhe por ele."""
    linhas = [f"Achei {len(candidatas)} clientes com esse nome. Repita com o número:"]
    for candidata in candidatas[:MAX_SUGESTOES]:
        linhas.append(candidata.rotulo)
    if len(candidatas) > MAX_SUGESTOES:
        linhas.append(f"(+{len(candidatas) - MAX_SUGESTOES} — refine o nome)")
    return "\n".join(linhas)


def formatar_particoes(familia: Sequence[Conta], *, comando: str) -> str:
    """Mãe + partições, cada uma com o comando pronto para copiar. Cada
    linha é uma conta de verdade, então o número já é o comando."""
    mae = familia[0]
    linhas = [
        f"{mae.numero} {mae.nome} tem {len(familia) - 1} partição(ões). "
        "Escolha de qual você precisa:"
    ]
    for conta in familia:
        sufixo = "" if conta is mae else "  (partição)"
        linhas.append(f"/{comando} {conta.numero} — {conta.nome}{sufixo}")
    return "\n".join(linhas)


def formatar_lista_clientes(contas: Sequence[Conta], *, filtro: str = "") -> str:
    """Lista de clientes. Partição aparece com a mãe ao lado, senão o
    técnico não sabe de qual local aquele número faz parte."""
    if not contas:
        alvo = f' com "{filtro}"' if filtro else ""
        return f"Nenhum cliente encontrado{alvo}."

    titulo = f'Clientes{f" — filtro: {filtro}" if filtro else ""} ({len(contas)})'
    linhas = [titulo, ""]
    for conta in dom_contas.ordenar(contas):
        vinculo = f"  [part. de {conta.conta_mae}]" if conta.e_particao else ""
        linhas.append(f"{conta.rotulo}{vinculo}")
    return "\n".join(linhas)


def filtrar_clientes(contas: Sequence[Conta], filtro: str) -> list[Conta]:
    """Filtro por nome ou número; sem filtro, devolve tudo."""
    alvo = normalizar(filtro)
    if not alvo:
        return list(contas)
    return [c for c in contas if alvo in normalizar(c.nome) or alvo in c.numero]


def formatar_ajuda() -> str:
    return (
        "Comandos:\n"
        "/relatorio <conta> [dias] — histórico de eventos, em .xls e .pdf "
        "(ex.: /relatorio 95 ou /relatorio 95 15)\n"
        "/zona <conta ou nome> — zoneamento do cliente "
        "(ex.: /zona 95 ou /zona auto mecanica)\n"
        "/clientes [filtro] — lista os clientes e as partições "
        "(ex.: /clientes ou /clientes villefort)\n"
        "/ajuda — esta lista\n\n"
        "A conta pode ser o número ou parte do nome. Se o nome casar com "
        "mais de um cliente, eu peço o número.\n"
        "Local com partição (tesouraria, depósito): cada uma tem número "
        "próprio. Se você pedir a conta principal, eu listo as partições "
        "para escolher."
    )


def formatar_resumo_relatorio(
    *, numero_conta: str, nome_cliente: str, dias: int, total_eventos: int
) -> str:
    return (
        f"Relatório — {numero_conta} {nome_cliente}\n"
        f"Últimos {dias} dia(s) · {total_eventos} evento(s)"
    ).rstrip()


def aviso_uso_interno() -> str:
    return "Uso interno — não repassar ao cliente."
