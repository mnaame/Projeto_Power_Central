from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.domain.dates import DataInvalidaError, parse_softguard_datetime

FUSO = ZoneInfo("America/Sao_Paulo")


@pytest.mark.parametrize(
    "bruto, esperado",
    [
        ("7/18/2026 3:45:00 PM", datetime(2026, 7, 18, 15, 45, 0, tzinfo=FUSO)),
        ("07/18/2026 03:45:00 PM", datetime(2026, 7, 18, 15, 45, 0, tzinfo=FUSO)),
        ("1/5/2026 12:00:00 AM", datetime(2026, 1, 5, 0, 0, 0, tzinfo=FUSO)),
        ("2026-07-18T15:45:00", datetime(2026, 7, 18, 15, 45, 0, tzinfo=FUSO)),
        ("2026-07-18T15:45:00.123", datetime(2026, 7, 18, 15, 45, 0, 123000, tzinfo=FUSO)),
    ],
)
def test_parse_formatos_conhecidos(bruto, esperado):
    assert parse_softguard_datetime(bruto) == esperado


@pytest.mark.parametrize(
    "bruto", [None, "", "   ", "1/1/1900 12:00:00 AM", "1900-01-01T00:00:00"]
)
def test_parse_valores_nulos(bruto):
    assert parse_softguard_datetime(bruto) is None


def test_parse_formato_desconhecido_levanta_erro():
    with pytest.raises(DataInvalidaError):
        parse_softguard_datetime("18-07-2026")
