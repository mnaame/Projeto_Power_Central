"""Diagnóstico automático da conta — lê eventos, escreve o problema em
português. Camada pura, sem rede.

Existe para o técnico não precisar abrir o `.xls`: o bot manda o arquivo e,
antes dele, um texto curto dizendo o que está errado naquela conta.

**Nada de regra nova sobre disparo aqui.** A classificação de disparo é a
do `domain/disparos.py`, reconciliada linha a linha contra planilha manual
— este módulo só agrupa o resultado dela por zona. Reimplementar a
contagem aqui criaria um segundo número para a mesma pergunta, e o dia em
que os dois divergissem ninguém saberia qual acreditar.

Os códigos de restauração (o evento de "voltou ao normal") não precisam de
lista própria: só é contado o que está nas listas de gatilho da
configuração, então restauração fica de fora por construção.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from app.domain import disparos as dom_disparos

SEVERIDADE_ALTA = 3
SEVERIDADE_MEDIA = 2
SEVERIDADE_BAIXA = 1

CODIGO_BYPASS = "BYP"
ZONA_SEM_NOME = "(sem zona)"

# Telegram corta em 4096; o diagnóstico é um resumo, não um relatório.
LIMITE_CARACTERES = 4096
# Quantas zonas citar quando o problema se espalha por muitas.
TOP_ZONAS = 3


@dataclass(frozen=True)
class Achado:
    """Um problema encontrado. `severidade` só ordena a saída — o que o
    técnico lê é o título e o detalhe."""

    severidade: int
    titulo: str
    detalhe: str


@dataclass(frozen=True)
class ConfigDiagnostico:
    """Limiares e códigos, todos vindos de `settings` (nada fixo no
    código): o código exato depende do modelo do painel de cada cliente,
    então a lista precisa ser ajustável sem mexer no sistema."""

    disparos_limiar: int = 5
    disparos_zona_limiar: int = 3
    bypass_limiar: int = 3
    comunicacao_limiar: int = 4
    comunicacao_por_dia_alta: float = 1.0
    codigos_comunicacao: tuple[str, ...] = ()
    codigos_painel_bateria: tuple[str, ...] = ()
    codigos_painel_ac: tuple[str, ...] = ()
    codigos_painel_tamper: tuple[str, ...] = ()
    zonas_ignoradas: tuple[str, ...] = field(
        default_factory=lambda: dom_disparos.ZONAS_IGNORADAS_PADRAO
    )


def _texto(valor: object) -> str:
    return str(valor).strip() if valor is not None else ""


def _codigo(evento: Mapping[str, object]) -> str:
    """Mesma estratégia defensiva do módulo de disparos: o nome do campo
    do código varia entre telas do portal."""
    for campo in ("rec_calarma", "cod_calarma", "rec_cCodigoAlarma", "codigo"):
        valor = _texto(evento.get(campo))
        if valor:
            return valor.upper()
    return ""


def _zona(evento: Mapping[str, object]) -> str:
    return _texto(evento.get("_zon_cdescripcion")) or ZONA_SEM_NOME


def _contar_por_codigo(eventos, codigos: Sequence[str]) -> int:
    alvo = {c.strip().upper() for c in codigos if c.strip()}
    if not alvo:
        return 0
    return sum(1 for e in eventos if _codigo(e) in alvo)


def _achados_disparos(eventos, *, cfg: ConfigDiagnostico, dias: int) -> list[Achado]:
    """Duas perguntas diferentes sobre o mesmo dado, e por isso dois
    achados:

    - **mesma zona repetindo** é um PONTO com problema (sensor com
      defeito, mal posicionado, animal, galho batendo) — dá para mandar
      o técnico direto nele;
    - **muitos disparos espalhados** é a CONTA com problema (instalação,
      uso, vizinhança) — exige outro tipo de visita.

    Juntar os dois num aviso só, como estava, escondia qual dos dois era.
    Pânico, rotina de entrada/saída e ciclo curto já vêm excluídos da
    regra validada em `domain/disparos.py`."""
    avaliados = dom_disparos.avaliar_disparos_da_conta(
        eventos, zonas_ignoradas=cfg.zonas_ignoradas
    )
    validos = [a for a in avaliados if a.valido]
    if not validos:
        return []

    por_zona = Counter(a.zona or ZONA_SEM_NOME for a in validos)
    periodo = f" em {dias} dia(s)" if dias else ""
    achados: list[Achado] = []

    reincidentes = [
        (zona, qtd) for zona, qtd in por_zona.most_common()
        if qtd >= cfg.disparos_zona_limiar
    ][:TOP_ZONAS]
    if reincidentes:
        citadas = ", ".join(f"{zona} ({qtd}x)" for zona, qtd in reincidentes)
        achados.append(
            Achado(
                severidade=SEVERIDADE_ALTA,
                titulo="Disparo repetido na mesma zona",
                detalhe=f"{citadas} — verificar o sensor/instalação desse ponto",
            )
        )

    if len(validos) >= cfg.disparos_limiar:
        achados.append(
            Achado(
                severidade=SEVERIDADE_MEDIA if reincidentes else SEVERIDADE_ALTA,
                titulo="Disparos no período",
                detalhe=(
                    f"{len(validos)} disparo(s){periodo}, "
                    f"em {len(por_zona)} zona(s): "
                    + ", ".join(f"{z} ({q})" for z, q in por_zona.most_common(TOP_ZONAS))
                ),
            )
        )
    return achados


def _achados_bypass(eventos, *, cfg: ConfigDiagnostico) -> list[Achado]:
    """Zona isolada muitas vezes costuma ser sensor com defeito ou mal
    posicionado — o cliente isola para parar de incomodar, e o ponto fica
    desprotegido sem ninguém notar."""
    por_zona = Counter(
        _zona(e) for e in eventos if _codigo(e) == CODIGO_BYPASS
    )
    achados = []
    for zona, qtd in por_zona.most_common(TOP_ZONAS):
        if qtd < cfg.bypass_limiar:
            break  # most_common já vem em ordem decrescente
        achados.append(
            Achado(
                severidade=SEVERIDADE_MEDIA,
                titulo="Zona isolada repetida",
                detalhe=f"{zona} isolada {qtd}x — possível sensor com defeito ou mal posicionado",
            )
        )
    return achados


def _achado_comunicacao(eventos, *, cfg: ConfigDiagnostico, dias: int) -> Achado | None:
    """O total levanta a suspeita; a MÉDIA POR DIA diz a gravidade.

    Sem a taxa, "300 falhas em 15 dias" (painel caindo o tempo todo) e
    "5 em 15 dias" (ruído) viravam exatamente o mesmo aviso, e o técnico
    não tinha como separar um do outro."""
    quantidade = _contar_por_codigo(eventos, cfg.codigos_comunicacao)
    if quantidade <= cfg.comunicacao_limiar:
        return None

    por_dia = quantidade / dias if dias else 0.0
    if por_dia >= cfg.comunicacao_por_dia_alta:
        return Achado(
            severidade=SEVERIDADE_ALTA,
            titulo="Comunicação instável",
            detalhe=(
                f"{quantidade} falha(s) de comunicação em {dias} dia(s) "
                f"(~{por_dia:.1f}/dia) — painel ficando off-line com frequência"
            ),
        )
    periodo = f" em {dias} dia(s)" if dias else " no período"
    return Achado(
        severidade=SEVERIDADE_MEDIA,
        titulo="Comunicação instável",
        detalhe=f"{quantidade} falha(s) de comunicação{periodo}",
    )


def _achados_painel(eventos, *, cfg: ConfigDiagnostico) -> list[Achado]:
    """Um evento já basta: bateria, violação e falta de energia não são
    'muitos ou pouco', são 'aconteceu'."""
    familias = (
        (cfg.codigos_painel_bateria, SEVERIDADE_ALTA, "Bateria baixa", "reportada {n} vez(es)"),
        (cfg.codigos_painel_tamper, SEVERIDADE_ALTA, "Violação/tamper", "{n} vez(es)"),
        (cfg.codigos_painel_ac, SEVERIDADE_MEDIA, "Falta de energia (AC)", "{n} vez(es)"),
    )
    achados = []
    for codigos, severidade, titulo, molde in familias:
        quantidade = _contar_por_codigo(eventos, codigos)
        if quantidade:
            achados.append(
                Achado(
                    severidade=severidade,
                    titulo=titulo,
                    detalhe=molde.format(n=quantidade),
                )
            )
    return achados


def diagnosticar(
    eventos: Sequence[Mapping[str, object]],
    *,
    cfg: ConfigDiagnostico,
    dias: int = 0,
) -> list[Achado]:
    """Achados da conta, do mais grave para o menos. Lista com um achado
    de severidade baixa quando não há nada a relatar — "sem problemas" é
    resposta, e o técnico precisa dela tanto quanto da outra."""
    achados: list[Achado] = []

    achados.extend(_achados_disparos(eventos, cfg=cfg, dias=dias))
    achados.extend(_achados_bypass(eventos, cfg=cfg))
    comunicacao = _achado_comunicacao(eventos, cfg=cfg, dias=dias)
    if comunicacao is not None:
        achados.append(comunicacao)
    achados.extend(_achados_painel(eventos, cfg=cfg))

    if not achados:
        return [
            Achado(
                severidade=SEVERIDADE_BAIXA,
                titulo="Sem problemas relevantes no período",
                detalhe="",
            )
        ]

    # `sorted` é estável: dentro da mesma severidade fica a ordem em que
    # as regras rodaram, que é a ordem em que elas importam.
    return sorted(achados, key=lambda a: a.severidade, reverse=True)


def formatar_diagnostico(
    achados: Sequence[Achado],
    *,
    numero_conta: str,
    nome_cliente: str,
    dias: int,
    limite: int = LIMITE_CARACTERES,
) -> str:
    """Texto pronto para o Telegram. Se não couber, corta pelos achados
    MENOS graves — o técnico tem que ver o pior, não o começo."""
    titulo = f"Diagnóstico — {numero_conta} {nome_cliente} (últimos {dias} dia(s))"
    linhas = [
        f"- {a.titulo}: {a.detalhe}" if a.detalhe else f"- {a.titulo}" for a in achados
    ]

    texto = "\n".join([titulo, *linhas])
    while len(texto) > limite and len(linhas) > 1:
        linhas.pop()
        texto = "\n".join([titulo, *linhas, "- (...)"])
    return texto[:limite]
