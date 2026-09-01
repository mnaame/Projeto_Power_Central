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

COMANDO_RELATORIO = "relatorio"
COMANDO_ZONA = "zona"
COMANDO_AJUDA = "ajuda"
COMANDOS_CONHECIDOS = (COMANDO_RELATORIO, COMANDO_ZONA, COMANDO_AJUDA)

# Quantos clientes listar quando o nome é ambíguo — a resposta tem que
# caber numa mensagem e continuar legível no celular.
MAX_SUGESTOES = 10

RESOLUCAO_OK = "ok"
RESOLUCAO_AMBIGUA = "ambigua"
RESOLUCAO_NAO_ENCONTRADA = "nao_encontrada"


@dataclass(frozen=True)
class Comando:
    """`nome` vazio = não é comando (texto solto) ou comando desconhecido."""

    nome: str
    argumentos: tuple[str, ...]


@dataclass(frozen=True)
class ContaResolvida:
    numero: str
    cue_iid: str
    nome: str


@dataclass(frozen=True)
class Resolucao:
    status: str  # RESOLUCAO_OK | RESOLUCAO_AMBIGUA | RESOLUCAO_NAO_ENCONTRADA
    conta: ContaResolvida | None
    candidatas: tuple[ContaResolvida, ...]


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


def resolver_conta(termo: str, mapa_contas: Mapping[str, tuple[str, str]]) -> Resolucao:
    """Aceita número (`95`, `0095`) ou parte do nome (`auto mecanica`).

    `mapa_contas` é o de `app.domain.tecnico.mapa_contas`: número
    normalizado -> (cue_iid, nome). Busca por nome ignora acento e caixa."""
    termo = (termo or "").strip()
    if not termo:
        return Resolucao(RESOLUCAO_NAO_ENCONTRADA, None, ())

    if termo.isdigit():
        numero = normalizar_conta(termo)
        achado = mapa_contas.get(numero)
        if achado is not None:
            return Resolucao(
                RESOLUCAO_OK, ContaResolvida(numero, achado[0], achado[1]), ()
            )
        return Resolucao(RESOLUCAO_NAO_ENCONTRADA, None, ())

    alvo = normalizar(termo)
    encontradas = [
        ContaResolvida(numero, cue_iid, nome)
        for numero, (cue_iid, nome) in mapa_contas.items()
        if alvo in normalizar(nome)
    ]
    if not encontradas:
        return Resolucao(RESOLUCAO_NAO_ENCONTRADA, None, ())

    # Nome idêntico (não só contido) resolve a ambiguidade: "VILLEFORT HM"
    # não pode ficar preso porque existe "VILLEFORT HM DEPOSITO".
    exatas = [c for c in encontradas if normalizar(c.nome) == alvo]
    if len(exatas) == 1:
        return Resolucao(RESOLUCAO_OK, exatas[0], ())
    if len(encontradas) == 1:
        return Resolucao(RESOLUCAO_OK, encontradas[0], ())

    encontradas.sort(key=lambda c: normalizar(c.nome))
    return Resolucao(RESOLUCAO_AMBIGUA, None, tuple(encontradas))


def formatar_ambiguidade(candidatas: Sequence[ContaResolvida]) -> str:
    """Lista curta para o técnico repetir o comando com o número — o bot
    nunca escolhe por ele."""
    linhas = [f"Achei {len(candidatas)} clientes com esse nome. Repita com o número:"]
    for candidata in candidatas[:MAX_SUGESTOES]:
        linhas.append(f"{candidata.numero} — {candidata.nome}")
    if len(candidatas) > MAX_SUGESTOES:
        linhas.append(f"(+{len(candidatas) - MAX_SUGESTOES} — refine o nome)")
    return "\n".join(linhas)


def formatar_ajuda() -> str:
    return (
        "Comandos:\n"
        "/relatorio <conta> [dias] — histórico de eventos "
        "(ex.: /relatorio 95 ou /relatorio 95 15)\n"
        "/zona <conta ou nome> — zoneamento do cliente "
        "(ex.: /zona 95 ou /zona auto mecanica)\n"
        "/ajuda — esta lista\n\n"
        "A conta pode ser o número ou parte do nome. "
        "Se o nome casar com mais de um cliente, eu peço o número."
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
