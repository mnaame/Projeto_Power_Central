"""Auditoria de horários de arme/desarme. Camada pura — sem I/O.

A regra é de uma linha só: **conta sem nenhuma linha de horário é conta
sem horário cadastrado**.

A varredura cobre **todas as contas**, sem recorte por tipo. Houve uma
versão anterior que auditava só as comerciais, partindo da ideia de que
residência não tem arme programado — mas quem opera a base quis ver todas,
residência inclusive. Isso apagou junto a consulta ao catálogo de tipos e a
camada que adivinhava o nome do campo de tipo entre as grafias do portal,
que era a parte do módulo nunca validada contra dados reais.

O recorte que sobrou é por número/nome (`nome_casa`), que não depende de
nada que o portal precise informar além do que já vem na lista de contas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class ContaAuditada:
    """Uma conta já classificada pela varredura."""

    conta: str
    nome: str
    resumo: str = ""

    @property
    def rotulo(self) -> str:
        return f"{self.conta} — {self.nome}"


def _texto(valor: object) -> str:
    return str(valor).strip() if valor is not None else ""


def tem_horario(rows: Sequence[Mapping[str, object]]) -> bool:
    """A regra do módulo: nenhuma linha = nenhum horário cadastrado."""
    return bool(rows)


def resumo_horario(rows: Sequence[Mapping[str, object]]) -> str:
    """Contagem + primeira faixa legível, para a coluna de referência da
    lista "com horário". Não tenta reconstruir a grade inteira: quem
    precisa do detalhe abre a conta no portal."""
    if not rows:
        return ""
    primeira = rows[0]
    abertura = _texto(primeira.get("hor_choraapertura"))
    fechamento = _texto(primeira.get("hor_choracierre"))
    faixa = f"{abertura}–{fechamento}" if abertura or fechamento else ""
    return f"{len(rows)} faixa(s) {faixa}".strip()


def nome_casa(item: ContaAuditada, busca: str) -> bool:
    """Recorte por número ou nome. Busca vazia não filtra nada."""
    termo = (busca or "").strip().lower()
    if not termo:
        return True
    return termo in item.nome.lower() or termo in item.conta.lower()


def filtrar_por_nome(itens: Sequence[ContaAuditada], busca: str) -> list[ContaAuditada]:
    return [i for i in itens if nome_casa(i, busca)]
