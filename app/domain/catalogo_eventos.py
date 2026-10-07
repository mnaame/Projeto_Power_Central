"""Catálogo de eventos — traduz a DESCRIÇÃO do evento no código dele.

Por que isto existe: o export da plataforma **não traz o código**. Na tela
aparece `NYR - Falha no Teste Periódico de Comunicação`, mas o arquivo
exportado guarda só a descrição. Medido contra a conta 118: 791 linhas de
dados, zero eventos legíveis, porque todo o sistema (disparo, arme,
desarme, comunicação, painel) é escrito em cima do código.

A alternativa seria reescrever cada regra para casar texto. Seria pior: a
regra de disparo é reconciliada linha a linha contra planilha manual, e
mexer nela para acomodar uma limitação do export trocaria uma regra
validada por uma heurística. Traduzindo aqui, na borda, tudo que vem
depois continua igual.

**O casamento é por descrição INTEIRA, não por pedaço.** "Restauração de
Disparo" contém "Disparo": casar por substring transformaria a volta ao
normal no próprio problema, inflando a contagem com o oposto do que se
quer medir.

O mapa padrão abaixo tem só o que foi confirmado em export real. O resto
vem da configuração `diag_descricoes` — o catálogo completo da plataforma
sai com `scripts/importar_catalogo_codigos.py`.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Mapping

# Descrição normalizada -> código. Só entradas CONFIRMADAS em export real
# (conta 118, 07/10). O resto vem da configuração: chutar aqui é como o
# `FST` do catálogo genérico, que não existe nesta base e fez o
# diagnóstico dizer "sem problemas" num painel caindo o dia inteiro.
MAPA_PADRAO: dict[str, str] = {
    "falha no teste periodico de comunicacao (painel de alarme off-line)": "NYR",
    "teste periodico de comunicacao ok": "TST",
    "alarme armado": "CLO",
    "fecho verificavel": "CLV",
    "alarme desarmado": "OPN",
    "desativacao enquanto o alarme tocava": "OPV",
    "restauracao de disparo": "RES",
}

_RE_ESPACOS = re.compile(r"\s+")
# A tela mostra "NYR - Descrição"; se algum dia o export passar a trazer o
# código junto, aproveitamos de graça em vez de depender do mapa.
_RE_CODIGO_NO_TEXTO = re.compile(r"^\s*([A-Z_][A-Z0-9]{2})\s*[-–—:]\s+")


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento e com espaços colapsados — o portal varia
    acentuação e espaçamento entre telas."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", (texto or "").strip().lower())
        if unicodedata.category(c) != "Mn"
    )
    return _RE_ESPACOS.sub(" ", sem_acento)


def mapa_de_texto(bruto: str) -> dict[str, str]:
    """Lê o mapa da configuração, no formato `descrição=CÓDIGO`, um por
    linha (ou separados por `;`). Linha sem `=` é ignorada em vez de
    derrubar o diagnóstico."""
    mapa: dict[str, str] = {}
    for pedaco in re.split(r"[;\n]", bruto or ""):
        if "=" not in pedaco:
            continue
        descricao, _, codigo = pedaco.partition("=")
        chave = normalizar(descricao)
        valor = codigo.strip().upper()
        if chave and valor:
            mapa[chave] = valor
    return mapa


def codigo_da_descricao(descricao: str, *, mapa: Mapping[str, str] | None = None) -> str:
    """Código do evento, ou string vazia quando a descrição é desconhecida.

    Desconhecido devolve vazio de propósito: evento que não se sabe o que
    é não pode virar palpite — ele aparece como "fora do catálogo" no
    script de calibragem, que é como se descobre o que falta mapear."""
    texto = (descricao or "").strip()
    if not texto:
        return ""

    embutido = _RE_CODIGO_NO_TEXTO.match(texto.upper())
    if embutido is not None:
        return embutido.group(1)

    return (mapa if mapa is not None else MAPA_PADRAO).get(normalizar(texto), "")
