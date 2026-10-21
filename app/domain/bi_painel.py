"""BI — o que a TELA diz, a partir do que `domain/bi.py` já calculou.

Camada pura: nenhum número novo é inventado aqui, só reorganizado para
ser entendido em cinco segundos. Nasceu de um problema real de leitura,
não de estética.

**O defeito que este módulo conserta.** Os três números do topo pareciam
falar da mesma coisa e tinham denominadores diferentes: "133
intervenções", "40% que melhorou" e "506,4 disparos evitados". O 40% era
4 de 10 — só dez visitas tinham base de comparação. Percentual grande
sobre amostra pequena não é um detalhe de apresentação: é o número ser
lido como se valesse para as 133.

Daí as três decisões que governam o arquivo:

1. **Percentual nunca anda sozinho.** Todo número relativo sai com o
   "de quantos" ao lado, e `funil()` existe para mostrar por que 133 e
   "4 de 10" convivem sem contradição.
2. **A unidade da manchete é a LOJA, não a visita.** Uma loja visitada
   cinco vezes conta uma vez em "melhorou" — senão a loja mais
   problemática, que é a mais visitada, domina a estatística. O funil faz
   a ponte entre as duas unidades às claras.
3. **Nada de falsa precisão.** "506,4 disparos evitados" é uma estimativa
   com uma casa decimal que a conta não sustenta; vira "~506".
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Mapping, Sequence

from app.domain.bi import (
    CLASSIFICACAO_ESTAVEL,
    CLASSIFICACAO_MELHOROU,
    CLASSIFICACAO_PIOROU,
    CLASSIFICACAO_SEM_BASE,
)

# Ordem de atenção: a tela abre no que precisa de ação. Uma loja que
# piorou vem antes de uma que melhorou mas ainda dispara muito, e dentro
# de cada grupo manda quem dispara mais hoje.
_ORDEM_SITUACAO = {
    CLASSIFICACAO_PIOROU: 0,
    CLASSIFICACAO_ESTAVEL: 1,
    CLASSIFICACAO_MELHOROU: 2,
}

ROTULO_SITUACAO = {
    CLASSIFICACAO_MELHOROU: "Melhorou",
    CLASSIFICACAO_PIOROU: "Piorou",
    CLASSIFICACAO_ESTAVEL: "Estável",
    CLASSIFICACAO_SEM_BASE: "Sem base",
}

# Ícone junto do rótulo: cor de status nunca carrega significado sozinha
# (daltonismo, impressão, tema preto).
ICONE_SITUACAO = {
    CLASSIFICACAO_MELHOROU: "▼",
    CLASSIFICACAO_PIOROU: "▲",
    CLASSIFICACAO_ESTAVEL: "=",
    CLASSIFICACAO_SEM_BASE: "–",
}

# Jargão que aparece na tela. Cada termo sai com um "?" e esta frase.
GLOSSARIO: dict[str, str] = {
    "sem_vinculo": (
        "A ordem foi concluída na Auvo, mas o cliente dela não está "
        "amarrado a nenhuma conta da PowerCentral no de-para — sem conta "
        "não há disparo para comparar."
    ),
    "sem_base": (
        "A loja não teve nenhum disparo válido na janela ANTES da visita. "
        "Sem disparo antes não há queda para medir: não é bom nem ruim, é "
        "não comparável."
    ),
    "com_base": (
        "A loja disparava antes da visita, então dá para comparar antes × "
        "depois. É o único grupo em que 'melhorou' ou 'piorou' significa "
        "alguma coisa."
    ),
    "estavel": (
        "A variação ficou dentro dos limiares configurados — nem queda nem "
        "aumento relevante."
    ),
    "cronico": (
        "Loja com visitas repetidas que CONTINUA disparando depois da mais "
        "recente. É o sinal de problema que a visita não resolve."
    ),
    "disparos_evitados": (
        "Estimativa de quantos disparos a menos ocorreram depois das "
        "visitas: soma de (disparos/dia antes − disparos/dia depois) × "
        "dias já decorridos. É uma estimativa, não uma contagem."
    ),
    "parcial": (
        "A janela de 'depois' ainda não fechou — o número desta loja ainda "
        "pode mudar."
    ),
}


def _normalizar_nome(texto: str) -> str:
    sem_acento = "".join(
        c
        for c in unicodedata.normalize("NFD", (texto or ""))
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(sem_acento.split())


# ----------------------------------------------------------------------
# Lojas por resultado — a lista em que se age
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class LojaResultado:
    """Uma loja, com as visitas comparáveis dela somadas."""

    conta_power: str
    nome_loja: str
    visitas: int
    antes_por_dia: float
    depois_por_dia: float
    variacao_pct: float | None
    classificacao: str
    parcial: bool
    ultima_visita: datetime

    @property
    def rotulo_situacao(self) -> str:
        return ROTULO_SITUACAO.get(self.classificacao, self.classificacao)

    @property
    def icone_situacao(self) -> str:
        return ICONE_SITUACAO.get(self.classificacao, "")

    @property
    def ordem(self) -> tuple[int, float]:
        return (_ORDEM_SITUACAO.get(self.classificacao, 9), -self.depois_por_dia)


def _classificar(
    antes: float, depois: float, *, limiar_melhora_pct: float, limiar_piora_pct: float
) -> tuple[float | None, str]:
    if antes <= 0:
        return None, CLASSIFICACAO_SEM_BASE
    variacao = (depois - antes) / antes * 100
    if variacao <= -limiar_melhora_pct:
        return variacao, CLASSIFICACAO_MELHOROU
    if variacao >= limiar_piora_pct:
        return variacao, CLASSIFICACAO_PIOROU
    return variacao, CLASSIFICACAO_ESTAVEL


def lojas_por_resultado(
    intervencoes: Iterable,
    *,
    limiar_melhora_pct: float,
    limiar_piora_pct: float,
) -> list[LojaResultado]:
    """Uma linha por loja, só com as visitas que tinham base.

    **Visita sem base fica de fora da soma**, não entra como zero. Incluir
    uma janela em que a loja não disparava puxaria o "antes" da loja para
    baixo e faria uma loja que nunca melhorou aparecer como melhorada — o
    erro que este painel inteiro existe para não cometer.

    O "antes" é a média das janelas (todas do mesmo tamanho); o "depois" é
    ponderado pelos dias já decorridos, porque uma visita de ontem tem
    muito menos dias medidos que uma de um mês atrás e não pode pesar
    igual.
    """
    por_conta: dict[str, list] = {}
    for item in intervencoes:
        if getattr(item, "classificacao", "") == CLASSIFICACAO_SEM_BASE:
            continue
        if float(getattr(item, "antes_por_dia", 0.0)) <= 0:
            continue
        conta = str(getattr(item, "conta_power", "") or "")
        if not conta:
            continue
        por_conta.setdefault(conta, []).append(item)

    lojas: list[LojaResultado] = []
    for conta, itens in por_conta.items():
        recente = max(itens, key=lambda i: i.marco)
        antes = sum(float(i.antes_por_dia) for i in itens) / len(itens)
        dias = sum(int(i.dias_depois) for i in itens)
        depois = (
            sum(float(i.depois_por_dia) * int(i.dias_depois) for i in itens) / dias
            if dias > 0
            else 0.0
        )
        variacao, classificacao = _classificar(
            antes,
            depois,
            limiar_melhora_pct=limiar_melhora_pct,
            limiar_piora_pct=limiar_piora_pct,
        )
        lojas.append(
            LojaResultado(
                conta_power=conta,
                nome_loja=str(getattr(recente, "nome_loja", "") or ""),
                visitas=len(itens),
                antes_por_dia=antes,
                depois_por_dia=depois,
                variacao_pct=variacao,
                classificacao=classificacao,
                parcial=any(bool(i.parcial) for i in itens),
                ultima_visita=recente.marco,
            )
        )

    lojas.sort(key=lambda loja: (loja.ordem, _normalizar_nome(loja.nome_loja)))
    return lojas


@dataclass(frozen=True)
class PlacarLojas:
    """O "4 de 10" — e o 10 nunca sai sem o 4, nem o 4 sem o 10."""

    total: int
    melhorou: int
    piorou: int
    estavel: int

    @property
    def pct_melhorou(self) -> float | None:
        return (self.melhorou / self.total * 100) if self.total else None


def placar(lojas: Sequence[LojaResultado]) -> PlacarLojas:
    return PlacarLojas(
        total=len(lojas),
        melhorou=sum(1 for loja in lojas if loja.classificacao == CLASSIFICACAO_MELHOROU),
        piorou=sum(1 for loja in lojas if loja.classificacao == CLASSIFICACAO_PIOROU),
        estavel=sum(1 for loja in lojas if loja.classificacao == CLASSIFICACAO_ESTAVEL),
    )


# ----------------------------------------------------------------------
# Disparos evitados — estimativa, e que se leia como estimativa
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class DisparosEvitados:
    valor: int  # sempre positivo; o sinal está em `direcao`
    direcao: str  # "menos" | "mais" | "neutro"

    @property
    def texto(self) -> str:
        if self.direcao == "neutro":
            return "sem diferença relevante"
        lado = "a menos" if self.direcao == "menos" else "a MAIS"
        return f"~{self.valor} disparos {lado}"


def disparos_evitados(bruto: float) -> DisparosEvitados:
    """"506.4" vira "~506". A casa decimal é precisão que a conta não
    tem — são taxas por dia multiplicadas por dias, somadas sobre janelas
    de tamanhos diferentes. Mostrar o ,4 convida a tratar a estimativa
    como contagem."""
    arredondado = round(float(bruto or 0.0))
    if arredondado == 0:
        return DisparosEvitados(valor=0, direcao="neutro")
    if arredondado > 0:
        return DisparosEvitados(valor=arredondado, direcao="menos")
    return DisparosEvitados(valor=-arredondado, direcao="mais")


# ----------------------------------------------------------------------
# De onde vêm os números
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class EtapaFunil:
    rotulo: str
    valor: int
    tipo: str  # "total" | "desconto" | "subtotal" | "resultado"
    termo: str = ""  # chave do GLOSSARIO, quando houver


def funil(
    resumo: Mapping[str, object], *, lojas: Sequence[LojaResultado]
) -> list[EtapaFunil]:
    """A conta que faz "133" e "4 de 10" conviverem.

    Sem ela os dois números parecem se contradizer, e um painel que
    parece se contradizer não é usado. A última ponte — de intervenções
    para lojas — é a que faltava: visitas repetidas na mesma loja somem
    aqui, de propósito."""
    def _int(chave: str) -> int:
        try:
            return int(resumo.get(chave, 0) or 0)
        except (TypeError, ValueError):
            return 0

    analisadas = _int("total_intervencoes")
    sem_vinculo = _int("sem_vinculo")
    sem_data = _int("sem_data")
    sem_base = _int("sem_base")
    com_base = analisadas - sem_base
    marcador = placar(lojas)

    etapas = [
        EtapaFunil("Ordens concluídas no período", analisadas + sem_vinculo + sem_data, "total"),
        EtapaFunil("sem vínculo com conta", sem_vinculo, "desconto", "sem_vinculo"),
    ]
    if sem_data:
        etapas.append(EtapaFunil("sem data de conclusão", sem_data, "desconto"))
    etapas += [
        EtapaFunil("Intervenções analisadas", analisadas, "subtotal"),
        EtapaFunil("sem base de comparação", sem_base, "desconto", "sem_base"),
        EtapaFunil("Intervenções com base", com_base, "subtotal", "com_base"),
        EtapaFunil("Lojas distintas (visitas repetidas somadas)", marcador.total, "subtotal"),
        EtapaFunil("Lojas que melhoraram", marcador.melhorou, "resultado"),
    ]
    return etapas


# ----------------------------------------------------------------------
# A frase — o item mais importante da tela
# ----------------------------------------------------------------------


def _juntar(partes: Sequence[str]) -> str:
    if len(partes) <= 1:
        return "".join(partes)
    return ", ".join(partes[:-1]) + " e " + partes[-1]


def frase_resumo(
    *,
    tecnico: str,
    total_intervencoes: int,
    lojas: Sequence[LojaResultado],
    evitados: DisparosEvitados,
    cronicos: int,
) -> str:
    """O painel inteiro em português, antes de qualquer gráfico.

    Quem abre a tela quer saber o que aconteceu, não operar um dashboard.
    A frase é gerada dos mesmos números dos cartões — se ela e um cartão
    discordarem, é bug, não arredondamento."""
    quem = tecnico.strip() or "a equipe"
    if total_intervencoes <= 0:
        return (
            f"No período não houve manutenção concluída de {quem} com cliente "
            "vinculado a uma conta — não há o que comparar."
        )

    visitas = "manutenção" if total_intervencoes == 1 else "manutenções"
    frases = [f"No período, {quem} fez {total_intervencoes} {visitas}."]

    marcador = placar(lojas)
    if not marcador.total:
        frases.append(
            "Nenhuma dessas lojas disparava antes da visita, então não houve "
            "base de comparação."
        )
    else:
        plural = "loja" if marcador.total == 1 else "lojas"
        pedacos = []
        if marcador.melhorou:
            pedacos.append(f"caíram em {marcador.melhorou}")
        if marcador.piorou:
            pedacos.append(f"pioraram em {marcador.piorou}")
        if marcador.estavel:
            pedacos.append(f"ficaram iguais em {marcador.estavel}")
        frases.append(
            f"Nas {marcador.total} {plural} que dava para comparar, os disparos "
            f"{_juntar(pedacos)}."
        )

    if evitados.direcao == "menos":
        frases.append(f"Estima-se ~{evitados.valor} disparos a menos.")
    elif evitados.direcao == "mais":
        frases.append(f"Estima-se ~{evitados.valor} disparos a MAIS depois das visitas.")

    if cronicos == 1:
        frases.append("1 loja segue crônica.")
    elif cronicos > 1:
        frases.append(f"{cronicos} lojas seguem crônicas.")

    return " ".join(frases)


# ----------------------------------------------------------------------
# Série semanal da tendência
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Semana:
    inicio: datetime
    rotulo: str
    visitas: int
    disparos_por_dia: float


def semanas(intervencoes: Iterable) -> list[Semana]:
    """Disparos/dia depois das visitas, agrupados por semana da visita.

    **Semana e não dia**, e barra e não linha, pelos dois motivos de
    sempre: 133 pontos numa linha de 640px viram um borrão, e uma linha
    ligando visitas esparsas sugere uma continuidade que o dado não tem —
    não existe série diária persistida aqui, só o que foi medido em volta
    de cada visita.

    Semana sem visita entra na lista com `visitas=0` e **sem barra**. Uma
    barra zerada diria "zero disparos naquela semana", que é diferente de
    "ninguém foi medido naquela semana"; e pular a semana encolheria o
    eixo do tempo calado.
    """
    itens = [i for i in intervencoes if getattr(i, "marco", None) is not None]
    if not itens:
        return []

    def _segunda(quando: datetime) -> datetime:
        dia = quando.replace(hour=0, minute=0, second=0, microsecond=0)
        return dia - timedelta(days=dia.weekday())

    agrupado: dict[datetime, list] = {}
    for item in itens:
        agrupado.setdefault(_segunda(item.marco), []).append(item)

    inicio = min(agrupado)
    fim = max(agrupado)
    saida: list[Semana] = []
    cursor = inicio
    while cursor <= fim:
        do_grupo = agrupado.get(cursor, [])
        dias = sum(int(i.dias_depois) for i in do_grupo)
        taxa = (
            sum(float(i.depois_por_dia) * int(i.dias_depois) for i in do_grupo) / dias
            if dias > 0
            else 0.0
        )
        saida.append(
            Semana(
                inicio=cursor,
                rotulo=cursor.strftime("%d/%m"),
                visitas=len(do_grupo),
                disparos_por_dia=taxa,
            )
        )
        cursor += timedelta(days=7)
    return saida


# ----------------------------------------------------------------------
# Antes × depois geral
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class AntesDepois:
    antes_por_dia: float
    depois_por_dia: float
    lojas: int

    @property
    def variacao_pct(self) -> float | None:
        if self.antes_por_dia <= 0:
            return None
        return (self.depois_por_dia - self.antes_por_dia) / self.antes_por_dia * 100

    @property
    def melhorou(self) -> bool:
        return self.depois_por_dia < self.antes_por_dia


def antes_depois_geral(lojas: Sequence[LojaResultado]) -> AntesDepois | None:
    """A base comparável inteira em dois números. Substitui o gráfico "por
    técnico", que com um técnico só era uma barrinha solitária dizendo o
    que o cartão já dizia."""
    if not lojas:
        return None
    return AntesDepois(
        antes_por_dia=sum(loja.antes_por_dia for loja in lojas) / len(lojas),
        depois_por_dia=sum(loja.depois_por_dia for loja in lojas) / len(lojas),
        lojas=len(lojas),
    )
