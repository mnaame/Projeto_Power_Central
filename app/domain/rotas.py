"""Rotas de visita preventiva — agrupa clientes por proximidade.

Camada pura, sem rede. O problema é simples de enunciar e cheio de
armadilhas de implementação: dado um punhado de coordenadas, quais
clientes dá para visitar na mesma saída?

**Por que limiar de distância e não "k grupos".** Um k-means precisaria
que alguém escolhesse o número de rotas, e o número certo não existe — ele
depende de como os clientes estão espalhados naquele dia. O limiar
responde a pergunta que a operação faz de verdade: "estes dois estão perto
o bastante para a mesma viagem?". Dois clientes entram na mesma rota se
estiverem a até `raio_km` um do outro, e isso é transitivo (A perto de B,
B perto de C ⇒ os três na mesma rota), que é exatamente como um corredor
de clientes ao longo de uma avenida deve ser tratado.

**Por que validar a região.** Parte das coordenadas do cadastro aponta
para outro estado — erro de digitação ou de origem. Uma coordenada errada
não atrapalha só a si mesma: ela entra num cluster e distorce o centroide,
levando a rota inteira para o lugar errado. Por isso a caixa delimitadora
é checada ANTES de agrupar, e o que cai fora é descartado como se não
tivesse coordenada.
"""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Sequence

RAIO_TERRA_KM = 6371.0

# Caixa de Minas Gerais / região metropolitana de BH. Coordenada fora
# disto é descartada: ver a nota do módulo sobre centroide.
LAT_MINIMA, LAT_MAXIMA = -21.5, -18.5
LON_MINIMA, LON_MAXIMA = -45.5, -43.0

# Casamento por nome é a reserva de quando não há de-para. O corte é alto
# de propósito: ligar o cliente errado a uma coordenada manda o técnico
# para o endereço de outra pessoa.
CORTE_NOME_PADRAO = 0.88

FONTE_AUVO = "Auvo"
FONTE_POWER = "PowerCentral"

# Clientes que não são clientes.
PADROES_INTERNOS = ("NOVO MILLENIUM", "NOVO MILLENNIUM", "CONTA TESTE")


@dataclass(frozen=True)
class PontoCliente:
    """Um cliente base já com coordenada resolvida."""

    conta: str
    nome: str
    cidade: str
    lat: float
    lon: float
    fonte: str


@dataclass
class Rota:
    """Um grupo de clientes visitáveis na mesma saída, já na ordem."""

    indice: int
    pontos: list[PontoCliente] = field(default_factory=list)

    @property
    def tamanho(self) -> int:
        return len(self.pontos)

    @property
    def centro(self) -> tuple[float, float]:
        return centroide(self.pontos)

    @property
    def extensao_km(self) -> float:
        """Soma das pernas na ordem de visita — serve para a equipe ver
        qual rota é curta e qual é esticada."""
        return round(
            sum(
                distancia_km(a.lat, a.lon, b.lat, b.lon)
                for a, b in zip(self.pontos, self.pontos[1:])
            ),
            1,
        )

    @property
    def cidades(self) -> str:
        vistas = []
        for ponto in self.pontos:
            if ponto.cidade and ponto.cidade not in vistas:
                vistas.append(ponto.cidade)
        return ", ".join(vistas)


def normalizar(texto: str) -> str:
    """Maiúsculas, sem acento e sem espaço sobrando — mesma régua usada
    para comparar nome de cliente no resto do sistema."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", (texto or "").upper())
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(sem_acento.split())


def e_interno(nome: str) -> bool:
    normalizado = normalizar(nome)
    return any(padrao in normalizado for padrao in PADROES_INTERNOS)


def coordenada_valida(lat: object, lon: object) -> tuple[float, float] | None:
    """Converte e valida contra a caixa da região. Devolve None para
    coordenada ausente, ilegível, zerada ou de fora.

    O caso `(0, 0)` tem nome — "ilha nula" — e é o que um cadastro vazio
    vira quando alguém salva o formulário sem preencher. Tratar como
    coordenada colocaria o cliente no Atlântico."""
    try:
        latitude = float(str(lat).strip().replace(",", ".")) if lat is not None else None
        longitude = float(str(lon).strip().replace(",", ".")) if lon is not None else None
    except (TypeError, ValueError):
        return None
    if latitude is None or longitude is None:
        return None
    if latitude == 0 and longitude == 0:
        return None
    if not (LAT_MINIMA <= latitude <= LAT_MAXIMA):
        return None
    if not (LON_MINIMA <= longitude <= LON_MAXIMA):
        return None
    return latitude, longitude


def coordenada_de_texto(bruto: object) -> tuple[float, float] | None:
    """Lê o formato `"lat,long"` da "Localização da conta" da
    PowerCentral, já validado pela região."""
    texto = str(bruto or "").strip()
    if "," not in texto:
        return None
    lat, _, lon = texto.partition(",")
    return coordenada_valida(lat, lon)


def distancia_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine. Distância em linha reta — não é distância de rua, e não
    precisa ser: serve para dizer quem está perto de quem, e a ordem de
    grandeza do erro não muda o agrupamento."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * RAIO_TERRA_KM * math.asin(min(1.0, math.sqrt(a)))


def centroide(pontos: Sequence[PontoCliente]) -> tuple[float, float]:
    if not pontos:
        return (0.0, 0.0)
    return (
        sum(p.lat for p in pontos) / len(pontos),
        sum(p.lon for p in pontos) / len(pontos),
    )


def semelhanca(a: str, b: str) -> float:
    return SequenceMatcher(None, normalizar(a), normalizar(b)).ratio()


def melhor_nome(nome: str, candidatos: Sequence[str], *, corte: float = CORTE_NOME_PADRAO) -> str:
    """Nome mais parecido acima do corte, ou vazio. Empate devolve o
    primeiro — determinístico, nunca arbitrário."""
    melhor, melhor_score = "", 0.0
    for candidato in candidatos:
        score = semelhanca(nome, candidato)
        if score > melhor_score:
            melhor, melhor_score = candidato, score
    return melhor if melhor_score >= corte else ""


class _UnionFind:
    """União por proximidade: se A está perto de B e B de C, os três vão
    para a mesma rota mesmo que A e C estejam longe. É o comportamento
    certo para clientes enfileirados ao longo de uma avenida."""

    def __init__(self, tamanho: int):
        self._pai = list(range(tamanho))

    def raiz(self, item: int) -> int:
        while self._pai[item] != item:
            self._pai[item] = self._pai[self._pai[item]]  # compressão de caminho
            item = self._pai[item]
        return item

    def unir(self, a: int, b: int) -> None:
        raiz_a, raiz_b = self.raiz(a), self.raiz(b)
        if raiz_a != raiz_b:
            self._pai[raiz_b] = raiz_a


def ordenar_visita(pontos: Sequence[PontoCliente]) -> list[PontoCliente]:
    """Vizinho mais próximo partindo de quem está mais perto do centroide.

    Não é a rota ótima (isso é o caixeiro-viajante), e não precisa ser:
    o objetivo é evitar o zigue-zague óbvio de uma lista em ordem
    alfabética. Quem dirige ajusta o resto."""
    restantes = list(pontos)
    if len(restantes) <= 2:
        return restantes

    # Empate de distância é comum (clientes equidistantes numa avenida) e
    # era desempatado pela ordem da lista — o que fazia a MESMA base sair
    # em ordens diferentes conforme a plataforma devolvesse os registros.
    # A conta entra como critério secundário para a saída ser sempre igual.
    centro_lat, centro_lon = centroide(restantes)
    atual = min(
        restantes,
        key=lambda p: (distancia_km(centro_lat, centro_lon, p.lat, p.lon), p.conta),
    )
    restantes.remove(atual)

    ordem = [atual]
    while restantes:
        referencia = atual
        proximo = min(
            restantes,
            key=lambda p: (distancia_km(referencia.lat, referencia.lon, p.lat, p.lon), p.conta),
        )
        restantes.remove(proximo)
        ordem.append(proximo)
        atual = proximo
    return ordem


def agrupar(pontos: Sequence[PontoCliente], *, raio_km: float) -> list[Rota]:
    """Agrupa por proximidade e ordena cada rota.

    As rotas saem da maior para a menor — é a ordem em que a operação
    decide o que fazer primeiro. O desempate é pela primeira conta, para
    que rodar duas vezes com os mesmos dados dê exatamente a mesma
    resposta."""
    total = len(pontos)
    if total == 0:
        return []

    uniao = _UnionFind(total)
    for i in range(total):
        for j in range(i + 1, total):
            if distancia_km(
                pontos[i].lat, pontos[i].lon, pontos[j].lat, pontos[j].lon
            ) <= raio_km:
                uniao.unir(i, j)

    grupos: dict[int, list[PontoCliente]] = {}
    for indice, ponto in enumerate(pontos):
        grupos.setdefault(uniao.raiz(indice), []).append(ponto)

    ordenados = sorted(
        grupos.values(),
        key=lambda g: (-len(g), min(p.conta for p in g)),
    )
    return [
        Rota(indice=numero, pontos=ordenar_visita(grupo))
        for numero, grupo in enumerate(ordenados, start=1)
    ]
