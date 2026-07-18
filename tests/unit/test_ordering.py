from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.domain.ordering import ordenar_por_falha_mais_antiga

FUSO = ZoneInfo("America/Sao_Paulo")


@dataclass
class _Item:
    nome: str
    tst_failure_since: datetime | None


def test_ordena_do_mais_antigo_para_o_mais_recente():
    itens = [
        _Item("b", datetime(2026, 7, 17, tzinfo=FUSO)),
        _Item("a", datetime(2026, 7, 16, tzinfo=FUSO)),
        _Item("c", datetime(2026, 7, 18, tzinfo=FUSO)),
    ]
    resultado = ordenar_por_falha_mais_antiga(itens)
    assert [i.nome for i in resultado] == ["a", "b", "c"]


def test_itens_sem_data_vao_para_o_final():
    itens = [
        _Item("sem_data", None),
        _Item("com_data", datetime(2026, 7, 16, tzinfo=FUSO)),
    ]
    resultado = ordenar_por_falha_mais_antiga(itens)
    assert [i.nome for i in resultado] == ["com_data", "sem_data"]
