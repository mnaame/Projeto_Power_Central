from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Mapping, Sequence

from app.domain.dates import parse_softguard_datetime

CODIGOS_COMPROVADORES_PADRAO: tuple[str, ...] = ("TST", "CLO", "OPN")
JANELA_HORAS_PADRAO = 3.0

SEM_COMUNICACAO = "sem_comunicacao"
FALSO_POSITIVO = "falso_positivo"

# Campos de "em falha de TST desde", em ordem de prioridade (1º, 2º, 3º
# teste — seção 5 do prompt). Usa-se a data do primeiro teste marcado
# com falha; se nenhum estiver marcado, cai para sta_dfechaultimotst.
_CAMPOS_FALHA_TST = (
    ("sta_ncuentaenfallodetst", "sta_tEnFalloDeTSTDesde"),
    ("sta_ncuentaenfallo2dotst", "sta_tEnFalloDeTST2Desde"),
    ("sta_ncuentaenfallo3ertst", "sta_tEnFalloDeTST3Desde"),
)


@dataclass(frozen=True)
class ContaClassificada:
    account_number: str
    account_name: str | None
    tst_failure_since: datetime | None
    last_event_code: str | None
    last_event_at: datetime | None
    classification: str


def _texto(valor: object) -> str | None:
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def normalizar_conta(
    bruta: Mapping[str, object],
) -> tuple[str, str | None, datetime | None, str | None, datetime | None]:
    """Extrai da resposta bruta de ``CuentaByDealer`` os campos usados pela
    regra de negócio (seção 6): número/nome da conta, data de início da
    falha de TST e o último evento recebido do painel."""
    numero = _texto(bruta.get("cue_ncuenta")) or ""
    nome = _texto(bruta.get("cue_cnombre"))

    falha_desde = None
    for campo_flag, campo_data in _CAMPOS_FALHA_TST:
        if _texto(bruta.get(campo_flag)) == "1":
            falha_desde = parse_softguard_datetime(bruta.get(campo_data))
            break
    if falha_desde is None:
        falha_desde = parse_softguard_datetime(bruta.get("sta_dfechaultimotst"))

    ultimo_evento_codigo = _texto(bruta.get("cue_cUltimaAlarmaRecibida"))
    ultimo_evento_data = parse_softguard_datetime(bruta.get("cue_dFechaUltimaAlarmaRecibida"))

    return numero, nome, falha_desde, ultimo_evento_codigo, ultimo_evento_data


def classificar_conta(
    bruta: Mapping[str, object],
    *,
    agora: datetime,
    janela_horas: float = JANELA_HORAS_PADRAO,
    codigos_comprovadores: Sequence[str] = CODIGOS_COMPROVADORES_PADRAO,
) -> ContaClassificada:
    """Aplica a regra de negócio da seção 6: uma conta em falha de TST está
    SEM COMUNICAÇÃO REAL quando o último evento recebido não é um código
    comprovador, ou é comprovador mas ocorreu fora da janela de N horas.
    Caso contrário (comprovador e dentro da janela) é FALSO POSITIVO.
    """
    numero, nome, falha_desde, evento_codigo, evento_data = normalizar_conta(bruta)

    codigos_normalizados = {c.upper() for c in codigos_comprovadores}
    comunicou_na_janela = (
        evento_codigo is not None
        and evento_codigo.upper() in codigos_normalizados
        and evento_data is not None
        and agora - evento_data <= timedelta(hours=janela_horas)
    )

    classificacao = FALSO_POSITIVO if comunicou_na_janela else SEM_COMUNICACAO

    return ContaClassificada(
        account_number=numero,
        account_name=nome,
        tst_failure_since=falha_desde,
        last_event_code=evento_codigo,
        last_event_at=evento_data,
        classification=classificacao,
    )


def classificar_contas(
    contas: Iterable[Mapping[str, object]],
    *,
    agora: datetime,
    janela_horas: float = JANELA_HORAS_PADRAO,
    codigos_comprovadores: Sequence[str] = CODIGOS_COMPROVADORES_PADRAO,
) -> list[ContaClassificada]:
    return [
        classificar_conta(
            bruta,
            agora=agora,
            janela_horas=janela_horas,
            codigos_comprovadores=codigos_comprovadores,
        )
        for bruta in contas
    ]
