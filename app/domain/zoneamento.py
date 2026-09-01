"""Zoneamento de uma conta: leitura das linhas cruas de `/Rest/Zona/` e
formatação para leitura no celular. Camada pura — sem I/O, sem Flask.

O zoneamento é o mapa de segurança do cliente (onde tem sensor, o que cada
um dispara). Quem envia decide para quem — aqui só se formata.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

# Largura da coluna de código na listagem. Os códigos reais vão de "1" a
# "18" e "SP1"/"SP2" (sentinella) — 4 acomoda todos sem desalinhar.
_LARGURA_CODIGO = 4


@dataclass(frozen=True)
class Zona:
    codigo: str
    descricao: str
    alarme: str  # código de alarme que a zona gera (ex.: NYR); pode ser vazio


def _texto(valor: object) -> str:
    # `zon_ccodigo` vem preenchido com espaços à direita no portal.
    return str(valor).strip() if valor is not None else ""


def zonas_da_resposta(linhas: Sequence[Mapping[str, object]]) -> list[Zona]:
    """Converte as linhas cruas do portal em `Zona`, preservando a ordem
    recebida (a consulta já pede `orderCodigo ASC`, que é a ordem da tela —
    numéricas primeiro, SP1/SP2 depois). Linha sem código é descartada:
    sem ele não há o que mostrar ao técnico."""
    zonas = []
    for linha in linhas:
        codigo = _texto(linha.get("zon_ccodigo"))
        if not codigo:
            continue
        zonas.append(
            Zona(
                codigo=codigo,
                descricao=_texto(linha.get("zon_cdescripcion")),
                alarme=_texto(linha.get("zon_cAlarmaAGenerar")),
            )
        )
    return zonas


def formatar_zoneamento(
    zonas: Sequence[Zona], *, numero_conta: str, nome_cliente: str
) -> str:
    """Texto monoespaçado: cabeçalho com conta/cliente/total e uma linha
    por zona (`código  descrição  (alarme)`). Quem envia é que quebra em
    várias mensagens se passar do limite do Telegram."""
    cabecalho = f"Zoneamento — {numero_conta} {nome_cliente}".rstrip()
    if not zonas:
        return f"{cabecalho}\nNenhuma zona cadastrada."

    largura_descricao = max(len(z.descricao) for z in zonas)
    linhas = [cabecalho, f"Total: {len(zonas)} zona(s)", ""]
    for zona in zonas:
        linha = f"{zona.codigo:<{_LARGURA_CODIGO}} {zona.descricao:<{largura_descricao}}"
        if zona.alarme:
            linha = f"{linha}  ({zona.alarme})"
        linhas.append(linha.rstrip())
    return "\n".join(linhas)
