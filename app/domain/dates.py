from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

FUSO_HORARIO = ZoneInfo("America/Sao_Paulo")

# Formatos observados na API SoftGuard (seção 5 do prompt): datas US com
# AM/PM e ISO com/sem milissegundos.
_FORMATOS = (
    "%m/%d/%Y %I:%M:%S %p",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
)


class DataInvalidaError(ValueError):
    """Levantado quando uma data da API SoftGuard não bate com nenhum
    formato conhecido — sinal de que o portal mudou o formato, não deve
    ser confundido com "sem data" (esse caso retorna None)."""


def parse_softguard_datetime(valor: object) -> datetime | None:
    """Converte uma data vinda da API SoftGuard para um ``datetime``
    timezone-aware em America/Sao_Paulo.

    Retorna ``None`` quando o valor é vazio ou é o sentinela "sem data"
    usado pelo portal (qualquer data com ano <= 1900, ex.: "1/1/1900
    12:00:00 AM"). Levanta ``DataInvalidaError`` para valores não vazios
    que não correspondem a nenhum formato conhecido.
    """
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None

    for formato in _FORMATOS:
        try:
            ingenuo = datetime.strptime(texto, formato)
        except ValueError:
            continue
        if ingenuo.year <= 1900:
            return None
        return ingenuo.replace(tzinfo=FUSO_HORARIO)

    raise DataInvalidaError(f"Formato de data não reconhecido: {texto!r}")
