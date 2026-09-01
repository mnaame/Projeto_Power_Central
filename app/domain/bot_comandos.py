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

from app.domain.contas import Conta, escolher_particao, tem_particoes

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

# Separador de partição no comando: `95/2` = conta 95, partição 2. A
# barra não colide com nada — o hífen colidiria com o formato que o
# portal mostra na tela ("MIL-0334") e o ponto pareceria decimal.
SEPARADOR_PARTICAO = "/"

# Quantos clientes listar quando o nome é ambíguo — a resposta tem que
# caber numa mensagem e continuar legível no celular.
MAX_SUGESTOES = 10

RESOLUCAO_OK = "ok"
RESOLUCAO_AMBIGUA = "ambigua"
RESOLUCAO_NAO_ENCONTRADA = "nao_encontrada"
# A conta tem partições e o técnico não disse qual: lista e pergunta.
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


def separar_conta_e_particao(termo: str) -> tuple[str, int | None]:
    """`95/2` -> ("95", 2). Sem barra, a partição fica indefinida (None) —
    diferente de 0, que é uma escolha explícita pela conta principal."""
    termo = (termo or "").strip()
    if SEPARADOR_PARTICAO not in termo:
        return termo, None
    base, _, sufixo = termo.rpartition(SEPARADOR_PARTICAO)
    sufixo = sufixo.strip()
    if not sufixo.isdigit():
        return termo, None
    return base.strip(), int(sufixo)


def resolver_conta(
    termo: str, contas_por_numero: Mapping[str, Sequence[Conta]]
) -> Resolucao:
    """Aceita número (`95`, `0095`), nome (`auto mecanica`) e partição
    (`95/2`).

    `contas_por_numero` é o de `app.domain.contas.agrupar_por_numero`:
    número normalizado -> partições daquela conta.

    Três perguntas em ordem, e nenhuma delas é chutada:
    1. qual cliente? (número ou nome; nome ambíguo pede o número)
    2. qual partição? (só quando a conta tem mais de uma e o técnico não
       disse qual — a partição errada é o setor errado do mesmo local)
    3. a partição pedida existe?"""
    termo, particao_pedida = separar_conta_e_particao(termo)
    if not termo:
        return Resolucao(RESOLUCAO_NAO_ENCONTRADA, None, ())

    if termo.isdigit():
        particoes = list(contas_por_numero.get(normalizar_conta(termo), ()))
    else:
        alvo = normalizar(termo)
        casadas = [
            (numero, list(particoes))
            for numero, particoes in contas_por_numero.items()
            if any(alvo in normalizar(c.nome) for c in particoes)
        ]
        if not casadas:
            return Resolucao(RESOLUCAO_NAO_ENCONTRADA, None, ())

        # Nome idêntico (não só contido) resolve a ambiguidade: "VILLEFORT
        # HM" não pode ficar preso porque existe "VILLEFORT HM DEPOSITO".
        exatas = [
            (numero, particoes)
            for numero, particoes in casadas
            if any(normalizar(c.nome) == alvo for c in particoes)
        ]
        if len(exatas) == 1:
            casadas = exatas
        if len(casadas) > 1:
            candidatas = [particoes[0] for _, particoes in casadas]
            candidatas.sort(key=lambda c: normalizar(c.nome))
            return Resolucao(RESOLUCAO_AMBIGUA, None, tuple(candidatas))
        particoes = casadas[0][1]

    if not particoes:
        return Resolucao(RESOLUCAO_NAO_ENCONTRADA, None, ())

    if particao_pedida is not None:
        escolhida = escolher_particao(particoes, particao_pedida)
        if escolhida is None:
            return Resolucao(RESOLUCAO_PARTICOES, None, tuple(particoes))
        return Resolucao(RESOLUCAO_OK, escolhida, ())

    if tem_particoes(particoes):
        return Resolucao(RESOLUCAO_PARTICOES, None, tuple(particoes))
    return Resolucao(RESOLUCAO_OK, particoes[0], ())


def formatar_ambiguidade(candidatas: Sequence[Conta]) -> str:
    """Lista curta para o técnico repetir o comando com o número — o bot
    nunca escolhe por ele."""
    linhas = [f"Achei {len(candidatas)} clientes com esse nome. Repita com o número:"]
    for candidata in candidatas[:MAX_SUGESTOES]:
        linhas.append(f"{candidata.numero} — {candidata.nome}")
    if len(candidatas) > MAX_SUGESTOES:
        linhas.append(f"(+{len(candidatas) - MAX_SUGESTOES} — refine o nome)")
    return "\n".join(linhas)


def formatar_particoes(candidatas: Sequence[Conta], *, comando: str) -> str:
    """Mostra o comando pronto para copiar — o técnico não precisa
    decorar a sintaxe da partição."""
    nome = candidatas[0].nome if candidatas else ""
    linhas = [
        f"{candidatas[0].numero} {nome} tem {len(candidatas)} partições. "
        "Escolha qual:"
    ]
    for candidata in candidatas:
        alvo = f"{candidata.numero}{SEPARADOR_PARTICAO}{candidata.particao}"
        linhas.append(f"/{comando} {alvo} — {candidata.nome}")
    return "\n".join(linhas)


def formatar_lista_clientes(contas: Sequence[Conta], *, filtro: str = "") -> str:
    """Lista de clientes com as partições. Ordena por número (é como a
    operação enxerga a base) e mostra a partição quando existe."""
    if not contas:
        alvo = f' com "{filtro}"' if filtro else ""
        return f"Nenhum cliente encontrado{alvo}."

    def _chave(conta: Conta):
        try:
            return (0, int(conta.numero), conta.particao)
        except ValueError:
            return (1, 0, conta.particao)

    titulo = f'Clientes{f" — filtro: {filtro}" if filtro else ""} ({len(contas)})'
    return "\n".join([titulo, ""] + [c.rotulo for c in sorted(contas, key=_chave)])


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
        "Conta com partições: use conta/partição — ex.: /zona 95/2. "
        "Se não disser qual, eu listo as partições."
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
