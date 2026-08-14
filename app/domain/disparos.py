from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Mapping, Sequence

from app.domain.dates import parse_softguard_datetime

# Regras B.3 do complemento de relatórios (validadas por reconciliação
# linha a linha contra planilhas manuais) — NÃO alterar sem flag de config.

CODIGO_DISPARO = "BUR"
CODIGOS_ARME = ("CLO", "CLV", "ROP")
CODIGOS_DESARME = ("OPN", "OPV", "RCL")

MINUTOS_ROTINA = 5  # BUR até 5 min APÓS arme / até 5 min ANTES de desarme = rotina
MINUTOS_CICLO_CURTO = 15  # arme seguido de desarme em até 15 min = ciclo de teste/engano

ZONAS_IGNORADAS_PADRAO: tuple[str, ...] = ("PANICO",)

OCORRENCIA_ALEATORIO = "ALEATORIO"
OCORRENCIA_RECORRENTE = "ALEATORIO E RECORRENTE"
LIMITE_RECORRENTE_PADRAO = 15

MOTIVO_ROTINA_ARME = "até 5 min após arme (rotina de saída)"
MOTIVO_ROTINA_DESARME = "até 5 min antes de desarme (rotina de entrada)"
MOTIVO_ZONA_IGNORADA = "zona ignorada (pânico)"
MOTIVO_CICLO_CURTO = "arme seguido de desarme em até 15 min (ciclo curto)"


@dataclass(frozen=True)
class DisparoAvaliado:
    quando: datetime | None
    zona: str
    id_evento: str
    atendido: bool
    valido: bool
    motivo_exclusao: str | None


@dataclass(frozen=True)
class ClienteComDisparos:
    conta_id: str
    conta_numero: str  # cue_ncuenta (número da conta no portal) — usado no de-para Auvo
    cliente: str
    quantidade: int
    ocorrencia: str
    zonas: tuple[str, ...]
    ids_eventos_atendidos: tuple[str, ...]  # p/ buscar tempo de conclusão (mais recente 1º)
    horarios: tuple[datetime, ...] = ()  # todos os disparos válidos, do mais antigo pro mais recente


def _texto(valor: object) -> str:
    return str(valor).strip() if valor is not None else ""


def _normalizar(texto: str) -> str:
    sem_acentos = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return sem_acentos.upper()


def zona_ignorada(
    descricao_zona: str, *, zonas_ignoradas: Sequence[str] = ZONAS_IGNORADAS_PADRAO
) -> bool:
    """Comparação sem acento e case-insensitive: "PÂNICO", "panico" e
    "Pânico" são todos ignorados com o padrão ("PANICO",)."""
    descricao = _normalizar(descricao_zona)
    return any(_normalizar(z) in descricao for z in zonas_ignoradas)


def _codigo_evento(evento: Mapping[str, object]) -> str:
    # nome do campo do código no p_recepcion pode variar; tenta os
    # candidatos conhecidos (mesma estratégia defensiva do módulo 1)
    for campo in ("rec_calarma", "cod_calarma", "rec_cCodigoAlarma", "codigo"):
        valor = _texto(evento.get(campo))
        if valor:
            return valor.upper()
    return ""


def _quando(evento: Mapping[str, object]) -> datetime | None:
    for campo in ("rec_tfechahora", "rec_tFechaHora", "rec_tFechaHoraRecepcion", "fecha"):
        if campo in evento:
            data = parse_softguard_datetime(evento.get(campo))
            if data is not None:
                return data
    return None


def _ciclos_curtos(
    armes: Sequence[datetime], desarmes: Sequence[datetime], *, limite: timedelta
) -> list[tuple[datetime, datetime]]:
    """Pareia cada arme com o desarme que o fecha (o próximo desarme na
    linha do tempo) e devolve só os ciclos cuja duração é <= limite —
    ciclos assim indicam um arme seguido de teste/engano, não um período
    armado de verdade."""
    eventos = sorted(
        [(t, "arme") for t in armes] + [(t, "desarme") for t in desarmes],
        key=lambda item: item[0],
    )
    ciclos: list[tuple[datetime, datetime]] = []
    for i, (t, tipo) in enumerate(eventos):
        if tipo != "arme":
            continue
        for t2, tipo2 in eventos[i + 1 :]:
            if tipo2 == "desarme":
                if t2 - t <= limite:
                    ciclos.append((t, t2))
                break
    return ciclos


def avaliar_disparos_da_conta(
    eventos: Sequence[Mapping[str, object]],
    *,
    zonas_ignoradas: Sequence[str] = ZONAS_IGNORADAS_PADRAO,
) -> list[DisparoAvaliado]:
    """Avalia os BUR de UMA conta contra os armes/desarmes dela (regra
    B.3): exclui rotina de entrada/saída e zonas de pânico. `eventos` são
    as linhas cruas do ReporteHistorico daquela conta (qualquer ordem)."""
    armes: list[datetime] = []
    desarmes: list[datetime] = []
    disparos: list[Mapping[str, object]] = []

    for evento in eventos:
        codigo = _codigo_evento(evento)
        quando = _quando(evento)
        if quando is None:
            if codigo == CODIGO_DISPARO:
                disparos.append(evento)
            continue
        if codigo in CODIGOS_ARME:
            armes.append(quando)
        elif codigo in CODIGOS_DESARME:
            desarmes.append(quando)
        elif codigo == CODIGO_DISPARO:
            disparos.append(evento)

    janela = timedelta(minutes=MINUTOS_ROTINA)
    ciclos_curtos = _ciclos_curtos(
        armes, desarmes, limite=timedelta(minutes=MINUTOS_CICLO_CURTO)
    )
    avaliados: list[DisparoAvaliado] = []

    for disparo in disparos:
        quando = _quando(disparo)
        zona = _texto(disparo.get("_zon_cdescripcion"))
        id_evento = _texto(disparo.get("rec_iid"))
        atendido = _texto(disparo.get("rec_ioperador")) not in ("", "0")

        motivo = None
        if zona and zona_ignorada(zona, zonas_ignoradas=zonas_ignoradas):
            motivo = MOTIVO_ZONA_IGNORADA
        elif quando is not None:
            if any(timedelta(0) <= quando - arme <= janela for arme in armes):
                motivo = MOTIVO_ROTINA_ARME
            elif any(timedelta(0) <= desarme - quando <= janela for desarme in desarmes):
                motivo = MOTIVO_ROTINA_DESARME
            elif any(inicio <= quando <= fim for inicio, fim in ciclos_curtos):
                motivo = MOTIVO_CICLO_CURTO

        avaliados.append(
            DisparoAvaliado(
                quando=quando,
                zona=zona,
                id_evento=id_evento,
                atendido=atendido,
                valido=motivo is None,
                motivo_exclusao=motivo,
            )
        )

    return avaliados


def filtrar_para_janela(
    eventos: Sequence[Mapping[str, object]], *, desde: datetime, hasta: datetime
) -> list[Mapping[str, object]]:
    """A consulta leva folga de 6 min em cada ponta SÓ para enxergar
    armes/desarmes na borda (regra B.2). Este filtro garante que apenas
    BUR de dentro do período contam como disparo — armes/desarmes da
    folga são mantidos para a avaliação de rotina."""
    resultado: list[Mapping[str, object]] = []
    for evento in eventos:
        codigo = _codigo_evento(evento)
        if codigo != CODIGO_DISPARO:
            resultado.append(evento)
            continue
        quando = _quando(evento)
        if quando is not None and desde <= quando <= hasta:
            resultado.append(evento)
    return resultado


def agrupar_por_conta(
    eventos: Sequence[Mapping[str, object]],
) -> dict[str, list[Mapping[str, object]]]:
    grupos: dict[str, list[Mapping[str, object]]] = {}
    for evento in eventos:
        conta_id = _texto(evento.get("rec_iidcuenta"))
        grupos.setdefault(conta_id, []).append(evento)
    return grupos


def consolidar_clientes(
    eventos: Sequence[Mapping[str, object]],
    *,
    zonas_ignoradas: Sequence[str] = ZONAS_IGNORADAS_PADRAO,
    limite_recorrente: int = LIMITE_RECORRENTE_PADRAO,
) -> list[ClienteComDisparos]:
    """Uma linha por cliente com disparos válidos (regra B.3/B.4):
    quantidade = TODOS os BUR válidos (sem agrupar), zonas distintas, e os
    ids dos disparos atendidos (mais recente primeiro) para o serviço
    buscar o tempo de conclusão via timeline."""
    resultado: list[ClienteComDisparos] = []

    for conta_id, eventos_da_conta in agrupar_por_conta(eventos).items():
        avaliados = avaliar_disparos_da_conta(
            eventos_da_conta, zonas_ignoradas=zonas_ignoradas
        )
        validos = [d for d in avaliados if d.valido]
        if not validos:
            continue

        cliente = ""
        for evento in eventos_da_conta:
            cliente = _texto(evento.get("cue_cnombre"))
            if cliente:
                break

        conta_numero = ""
        for evento in eventos_da_conta:
            conta_numero = _texto(evento.get("cue_ncuenta"))
            if conta_numero:
                break

        zonas_distintas: list[str] = []
        for d in validos:
            if d.zona and d.zona not in zonas_distintas:
                zonas_distintas.append(d.zona)

        atendidos_recentes = sorted(
            (d for d in validos if d.atendido and d.quando is not None),
            key=lambda d: d.quando,
            reverse=True,
        )
        horarios = tuple(
            sorted(d.quando for d in validos if d.quando is not None)
        )

        quantidade = len(validos)
        resultado.append(
            ClienteComDisparos(
                conta_id=conta_id,
                conta_numero=conta_numero,
                cliente=cliente,
                quantidade=quantidade,
                ocorrencia=(
                    OCORRENCIA_RECORRENTE
                    if quantidade >= limite_recorrente
                    else OCORRENCIA_ALEATORIO
                ),
                zonas=tuple(zonas_distintas),
                ids_eventos_atendidos=tuple(d.id_evento for d in atendidos_recentes),
                horarios=horarios,
            )
        )

    resultado.sort(key=lambda c: c.quantidade, reverse=True)
    return resultado
