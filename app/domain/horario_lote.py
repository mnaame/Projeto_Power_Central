"""Ajuste de horário em lote — cálculo do novo fechamento. Camada pura.

Este é o único módulo do sistema que **escreve** no cadastro da
plataforma, e escreve na base inteira. A parte que decide o que vai ser
gravado mora aqui, sem rede, porque é a parte que precisa ser testada
exaustivamente antes de tocar em qualquer conta real.

**A regra da meia-noite.** Somar o delta pode levar o fechamento para
00:00 ou além. Isso NÃO é tratado como "virou o dia": é tratado como
**não mexer**. O motivo é que `hor_ndiacierre` (o dia do fechamento)
teria que mudar junto, e isso é uma decisão sobre a grade de horário do
cliente — não uma conta aritmética. Quem decide isso é uma pessoa olhando
o caso, então a linha vai para uma lista de trabalho manual em vez de ser
alterada por chute.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence

MINUTOS_DO_DIA = 24 * 60

# "HH:MM" ou "HH:MM:SS" — o portal usa o primeiro, mas aceitar os dois
# custa nada e evita uma falha boba se mudarem.
_RE_HORA = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::\d{2})?\s*$")

CATEGORIA_APLICAR = "aplicar"
CATEGORIA_MANUAL = "manual"
CATEGORIA_INVALIDO = "invalido"

DIAS_SEMANA = {
    1: "domingo",
    2: "segunda",
    3: "terça",
    4: "quarta",
    5: "quinta",
    6: "sexta",
    7: "sábado",
}


@dataclass(frozen=True)
class LinhaHorario:
    """Uma linha de horário do portal, já com o cálculo resolvido."""

    horario_id: str
    cue_iid: str
    conta: str
    nome: str
    dia_abertura: int
    hora_abertura: str
    dia_fechamento: int
    antes: str
    depois: str  # vazio quando não vai ser alterada
    categoria: str

    @property
    def dia_legivel(self) -> str:
        return DIAS_SEMANA.get(self.dia_fechamento, str(self.dia_fechamento))

    @property
    def de_para(self) -> str:
        return f"{self.antes} → {self.depois}" if self.depois else self.antes


def minutos_da_hora(hhmm: str) -> int | None:
    """"HH:MM" -> minutos desde meia-noite, ou None se não for hora."""
    encontrado = _RE_HORA.match(hhmm or "")
    if encontrado is None:
        return None
    horas, minutos = int(encontrado.group(1)), int(encontrado.group(2))
    if horas > 23 or minutos > 59:
        return None
    return horas * 60 + minutos


def hora_dos_minutos(minutos: int) -> str:
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def novo_fechamento(hhmm: str, delta_min: int) -> tuple[str | None, bool]:
    """Devolve `(novo_horario, vira_meia_noite)`.

    - `("19:00", False)` — pode aplicar;
    - `(None, True)` — passaria da meia-noite: **não altera**, vai para a
      lista manual;
    - `(None, False)` — a hora atual não é legível, então não há o que
      calcular. Também não altera: um valor que não se entende é o último
      lugar onde se deve escrever por cima."""
    atual = minutos_da_hora(hhmm)
    if atual is None:
        return None, False

    novo = atual + delta_min
    if novo >= MINUTOS_DO_DIA or novo < 0:
        return None, True
    return hora_dos_minutos(novo), False


def _texto(valor: object) -> str:
    return str(valor).strip() if valor is not None else ""


def _inteiro(valor: object) -> int:
    try:
        return int(float(_texto(valor) or 0))
    except ValueError:
        return 0


def preparar_linhas(
    linhas_portal: Sequence[Mapping[str, object]],
    *,
    conta: str,
    nome: str,
    delta_min: int,
) -> list[LinhaHorario]:
    """Converte as linhas cruas de `listar_horarios` em `LinhaHorario`, já
    classificadas. Linha sem `Id` é descartada: sem ele não há o que
    gravar."""
    preparadas: list[LinhaHorario] = []
    for linha in linhas_portal:
        horario_id = _texto(linha.get("Id"))
        if not horario_id:
            continue

        antes = _texto(linha.get("hor_choracierre"))
        depois, vira = novo_fechamento(antes, delta_min)
        if depois is not None:
            categoria = CATEGORIA_APLICAR
        elif vira:
            categoria = CATEGORIA_MANUAL
        else:
            categoria = CATEGORIA_INVALIDO

        preparadas.append(
            LinhaHorario(
                horario_id=horario_id,
                cue_iid=_texto(linha.get("hor_iidcuenta")),
                conta=conta,
                nome=nome,
                dia_abertura=_inteiro(linha.get("hor_ndiaapertura")),
                hora_abertura=_texto(linha.get("hor_choraapertura")),
                dia_fechamento=_inteiro(linha.get("hor_ndiacierre")),
                antes=antes,
                depois=depois or "",
                categoria=categoria,
            )
        )
    return preparadas


def corpo_do_put(linha_portal: Mapping[str, object], *, novo_fechamento_hhmm: str) -> dict:
    """Corpo do PUT, montado a partir da linha **recém-lida** do portal.

    Só `hor_choracierre` muda; todo o resto é eco do que está lá. Os
    campos são listados explicitamente (em vez de copiar o dicionário
    inteiro) porque é o conjunto confirmado no HAR — mandar campo extra
    que o portal não espera é risco desnecessário numa chamada de
    escrita."""
    return {
        "Id": linha_portal.get("Id"),
        "Name": linha_portal.get("Name") or "",
        "hor_iidcuenta": linha_portal.get("hor_iidcuenta"),
        "hor_ndiaapertura": linha_portal.get("hor_ndiaapertura"),
        "hor_choraapertura": linha_portal.get("hor_choraapertura"),
        "hor_ndiacierre": linha_portal.get("hor_ndiacierre"),
        "hor_choracierre": novo_fechamento_hhmm,
    }
