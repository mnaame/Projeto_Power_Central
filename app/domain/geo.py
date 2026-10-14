"""Coordenadas: reconhecer, validar e medir distância.

Camada pura, sem rede. Este código nasceu no agrupamento por raio em km,
que foi substituído pelo catálogo por bairro — mas a coordenada continua
valendo por outro motivo: é ela que coloca o cliente no mapa.

**Por que validar a região.** Parte das coordenadas do cadastro aponta
para outro estado: na base real, 13 das 104 contas com coordenada caíam
no interior de São Paulo. No mapa isso não é um detalhe — é um cliente
plantado a 400 km de onde ele está, e o mapa inteiro abrindo no
enquadramento errado por causa dele. Por isso a caixa delimitadora é
checada antes de qualquer uso, e o que cai fora é tratado como se não
tivesse coordenada.

**Por que achar pela forma e não pelo nome do campo.** Chutar nome de
campo já custou uma rodada inteira deste módulo: a versão que procurava
`cue_clocalizacion` devolveu 105 contas sem coordenada, zero, sem um
único erro na tela. Um par de coordenadas se identifica sozinho.
"""

from __future__ import annotations

import math
import re

# Caixa de Minas Gerais / região metropolitana de BH.
LAT_MINIMA, LAT_MAXIMA = -21.5, -18.5
LON_MINIMA, LON_MAXIMA = -45.5, -43.0

RAIO_TERRA_KM = 6371.0

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


# Dois números decimais — e só dois. Casa tanto "-19.91,-43.94" (ponto
# decimal, vírgula separando) quanto "-19,91,-43,94" (vírgula nos dois
# papéis), que o `partition(",")` da primeira versão quebrava.
_RE_PAR_DECIMAL = re.compile(r"-?\d+[.,]\d+")


def coordenada_de_texto(bruto: object) -> tuple[float, float] | None:
    """Lê um par "lat,long" de um texto, já validado pela região."""
    numeros = _RE_PAR_DECIMAL.findall(str(bruto or ""))
    if len(numeros) != 2:
        return None
    return coordenada_valida(numeros[0], numeros[1])


# Nomes de campo tentados quando a coordenada vem em DOIS campos.
CHAVES_LAT = ("latitude", "lat")
CHAVES_LON = ("longitude", "lng", "lon")


def coordenada_do_registro(registro) -> tuple[float, float] | None:
    """Acha a coordenada em qualquer registro, **sem depender do nome do
    campo**.

    Isto existe porque chutar nome de campo já custou caro: a primeira
    versão procurava `cue_clocalizacion` na conta da PowerCentral, o campo
    tem outro nome, e o resultado foi 105 contas sem coordenada — zero,
    sem nenhum erro aparecendo. Um par de coordenadas se identifica
    sozinho (dois decimais, ou um par lat/lon), então é por aí que ele é
    procurado, em vez de por nome.

    Ordem: primeiro os campos com nome de latitude/longitude, depois
    qualquer campo de texto que contenha um par "lat,long", e por fim os
    sub-registros (a Auvo aninha endereço). A caixa da região é validada
    em todos os caminhos — é ela que impede um par de números qualquer
    (um valor monetário, um CEP) de passar por coordenada."""
    if not isinstance(registro, dict):
        return None

    normalizados = {str(k).strip().lower(): v for k, v in registro.items()}
    for chave_lat in CHAVES_LAT:
        if chave_lat not in normalizados:
            continue
        for chave_lon in CHAVES_LON:
            if chave_lon in normalizados:
                achado = coordenada_valida(
                    normalizados[chave_lat], normalizados[chave_lon]
                )
                if achado is not None:
                    return achado

    for valor in registro.values():
        if isinstance(valor, str):
            achado = coordenada_de_texto(valor)
            if achado is not None:
                return achado

    for valor in registro.values():
        achado = None
        if isinstance(valor, dict):
            achado = coordenada_do_registro(valor)
        elif isinstance(valor, (list, tuple)):
            for item in valor:
                achado = coordenada_do_registro(item)
                if achado is not None:
                    break
        if achado is not None:
            return achado
    return None


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
