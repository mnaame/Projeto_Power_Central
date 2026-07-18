from __future__ import annotations

from datetime import datetime


def formatar_duracao(desde: datetime | None, agora: datetime) -> str:
    """Duração decorrida entre `desde` e `agora`, formatada como "1d 2h 3min"
    (regra 5 — usada tanto no relatório do Telegram quanto no painel web)."""
    if desde is None:
        return "desconhecido"
    total_minutos = max(int((agora - desde).total_seconds() // 60), 0)
    dias, resto_min = divmod(total_minutos, 24 * 60)
    horas, minutos = divmod(resto_min, 60)
    partes = []
    if dias:
        partes.append(f"{dias}d")
    if dias or horas:
        partes.append(f"{horas}h")
    partes.append(f"{minutos}min")
    return " ".join(partes)
