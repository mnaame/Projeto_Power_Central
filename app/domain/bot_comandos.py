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

    pediu_pelo_numero = termo.isdigit()
    if pediu_pelo_numero:
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
    # Número explícito é resposta, não pergunta. Perguntar de novo aqui
    # deixava a conta MÃE inalcançável: ela sempre tem partição, então
    # /relatorio 154 caía na mesma pergunta pra sempre (visto em produção).
    if pediu_pelo_numero:
        return Resolucao(RESOLUCAO_OK, conta, ())

    familia = dom_contas.familia(contas, conta)
    if len(familia) > 1:
        return Resolucao(RESOLUCAO_PARTICOES, None, tuple(familia))
    return Resolucao(RESOLUCAO_OK, conta, ())


def _opcoes(contas: Sequence[Conta], *, comando: str, marcar_particao: bool) -> list[str]:
    """Nome numa linha, comando SOZINHO na seguinte.

    O comando não pode dividir a linha com o nome do cliente: no Telegram
    o técnico copia (ou toca) a linha inteira, e aí chega
    `/relatorio 154 — APOIO TIROL FILIAL 503`, que o bot lê como um nome
    de cliente e não acha nada. Aconteceu em produção."""
    linhas = []
    for conta in contas:
        marca = "  (partição)" if marcar_particao and conta.e_particao else ""
        linhas.append(f"{conta.nome}{marca}")
        linhas.append(f"/{comando} {conta.numero}")
        linhas.append("")
    return linhas


def formatar_ambiguidade(candidatas: Sequence[Conta], *, comando: str) -> str:
    """Lista curta para o técnico escolher — o bot nunca escolhe por ele."""
    mostradas = list(candidatas[:MAX_SUGESTOES])
    linhas = [f"Achei {len(candidatas)} clientes com esse nome. Escolha um:", ""]
    linhas += _opcoes(mostradas, comando=comando, marcar_particao=True)
    if len(candidatas) > MAX_SUGESTOES:
        linhas.append(f"(+{len(candidatas) - MAX_SUGESTOES} — refine o nome)")
    return "\n".join(linhas).rstrip()


def formatar_particoes(familia: Sequence[Conta], *, comando: str) -> str:
    """Mãe + partições, cada uma com o comando pronto para copiar."""
    mae = familia[0]
    quantas = len(familia) - 1
    plural = "partição separada" if quantas == 1 else f"{quantas} partições separadas"
    linhas = [
        f"{mae.nome} tem {plural if quantas != 1 else '1 ' + plural}. "
        "Escolha de qual você precisa:",
        "",
    ]
    linhas += _opcoes(familia, comando=comando, marcar_particao=True)
    return "\n".join(linhas).rstrip()


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


def aviso_uso_interno() -> str:
    return "Uso interno — não repassar ao cliente."


def formatar_ajuda(*, dias_padrao: int, cooldown_segundos: int = 0) -> str:
    """Referência completa, escrita para ser lida no celular: um bloco por
    comando, exemplo em toda linha. `dias_padrao` vem da configuração —
    escrever "7" fixo aqui viraria mentira no dia em que mudarem."""
    linhas = [
        "COMANDOS DO BOT",
        "",
        "/relatorio <conta> [dias]",
        "  Histórico de eventos da conta, em .xls (abre no PC, com as",
        "  cores da plataforma) e .pdf (abre no celular).",
        f"  Sem informar os dias, usa {dias_padrao}.",
        "  Ex.: /relatorio 95        /relatorio 95 15",
        "",
        "/zona <conta ou nome>",
        "  Zoneamento do cliente: número da zona, descrição e o alarme",
        "  que ela gera.",
        "  Ex.: /zona 95        /zona auto mecanica",
        "",
        "/clientes [filtro]",
        "  Lista os clientes, já com as partições. O filtro vale para",
        "  nome ou número.",
        "  Ex.: /clientes        /clientes villefort",
        "",
        "/ajuda",
        "  Esta lista.",
        "",
        "COMO INFORMAR A CONTA",
        "  Pelo número (95, 0095) ou por parte do nome (auto mecanica).",
        "  Se o nome casar com mais de um cliente, eu mostro a lista e",
        "  peço o número — nunca escolho por você.",
        "",
        "LOCAL COM PARTIÇÃO (tesouraria, depósito)",
        "  Cada setor é uma conta com número próprio. Pedindo pelo",
        "  NÚMERO, eu vou direto nele. Buscando pelo NOME, se o local",
        "  tiver setores eu listo todos para você escolher.",
        "  Use /clientes para ver quais são: a partição aparece com",
        "  [part. de <conta>] do lado.",
    ]
    if cooldown_segundos > 0:
        linhas += [
            "",
            f"RITMO: {cooldown_segundos}s entre um pedido e outro, por pessoa —",
            "  cada consulta puxa dado da PowerCentral.",
        ]
    linhas += ["", aviso_uso_interno()]
    return "\n".join(linhas)


def formatar_resumo_relatorio(
    *, numero_conta: str, nome_cliente: str, dias: int, total_eventos: int
) -> str:
    return (
        f"Relatório — {numero_conta} {nome_cliente}\n"
        f"Últimos {dias} dia(s) · {total_eventos} evento(s)"
    ).rstrip()


