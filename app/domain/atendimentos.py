from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence

from app.domain.dates import parse_softguard_datetime
from app.domain.formatting import formatar_duracao_hms

# Regras A.3 do complemento de relatórios (validadas em campo contra
# planilhas manuais) — NÃO alterar sem flag de config.

CODIGOS_FECHAMENTO = ("122", "133")  # códigos de fechamento validados (122 e 133)
ACAO_INICIO = "Inicio"
ACAO_AUTOPROCESO = "Autoproceso"
ACAO_COMENTARIO = "IngresoComentarios"
PREFIXO_COMENTARIO_AUTOMATICO = "--- PROCEDIMENTO"
MONITOR_AUTOMATICO = "Automático"

TERMOS_ARME_PADRAO: tuple[str, ...] = ("ativado", "armado remotamente", "armamento confirmado")

_DIAS_SEMANA = ("SEG", "TER", "QUA", "QUI", "SEX", "SAB", "DOM")

# Palavras de negação: se aparecem logo antes do termo de arme, o texto
# NÃO indica arme ("ainda NÃO foi ativado" — caso validado pela operação).
_NEGACOES = ("nao", "nem", "sem")
_JANELA_NEGACAO_PALAVRAS = 4

INCLUIDO = "incluido"
DESCARTADO = "descartado"
ABERTO = "aberto"


@dataclass(frozen=True)
class AnaliseTimeline:
    inicio: datetime | None
    fechamento: datetime | None
    fechado_por_autoproceso: bool
    monitor: str | None
    situacao: str | None
    chamada: datetime | None


@dataclass(frozen=True)
class AtendimentoProcessado:
    data_evento: datetime | None
    conta: str
    cliente: str
    evento: str
    situacao: str
    tempo_atendimento: str
    monitor: str
    status: str  # INCLUIDO | DESCARTADO | ABERTO
    motivo_descarte: str | None


def _texto(valor: object) -> str:
    return str(valor).strip() if valor is not None else ""


def _sem_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


def _normalizar_para_busca(texto: str) -> str:
    return _sem_acentos(texto).lower()


def _passos_ordenados(passos: Sequence[Mapping[str, object]]) -> list[dict]:
    com_data = []
    for passo in passos:
        quando = parse_softguard_datetime(passo.get("etl_tFechaHora"))
        com_data.append({"quando": quando, **passo})
    # ordena por data; passos sem data vão para o fim mantendo ordem original
    return sorted(
        com_data,
        key=lambda p: (p["quando"] is None, p["quando"] or datetime.max.replace(tzinfo=None)),
    )


def _e_fechamento(passo: Mapping[str, object]) -> bool:
    if _texto(passo.get("etl_iAccionCode")) in CODIGOS_FECHAMENTO:
        return True
    acao = _texto(passo.get("etl_cAccion"))
    if acao == ACAO_AUTOPROCESO:
        return True
    texto_completo = _normalizar_para_busca(
        f"{acao} {_texto(passo.get('etl_cObservacion'))}"
    )
    return "processado" in texto_completo


def _e_chamada(passo: Mapping[str, object]) -> bool:
    # Chamada ATENDIDA: ação LlamadoTelefonico + observação com "Atendida"
    # (regra do motor validado em produção). Só a ligação atendida conta —
    # uma "Chamada não atendida" (contém "atendida" como substring) não vira
    # tempo para ligar.
    acao = _normalizar_para_busca(_texto(passo.get("etl_cAccion")))
    obs = _normalizar_para_busca(_texto(passo.get("etl_cObservacion")))
    if "llamadotelefonico" not in acao:
        return False
    return "atendida" in obs and "nao atendida" not in obs


def analisar_timeline(passos: Sequence[Mapping[str, object]]) -> AnaliseTimeline:
    """Extrai da linha do tempo: início, fechamento, monitor, situação e
    momento da chamada ao cliente (regras A.3 / B.5). Sem fechamento =
    evento em aberto."""
    ordenados = _passos_ordenados(passos)

    inicio = None
    for passo in ordenados:
        if _texto(passo.get("etl_cAccion")) == ACAO_INICIO:
            inicio = passo["quando"]
            break

    chamada = None
    for passo in ordenados:
        if _e_chamada(passo):
            chamada = passo["quando"]
            break

    passo_fechamento = None
    for passo in ordenados:
        if _e_fechamento(passo):
            passo_fechamento = passo
            break

    if passo_fechamento is None:
        return AnaliseTimeline(
            inicio=inicio,
            fechamento=None,
            fechado_por_autoproceso=False,
            monitor=None,
            situacao=_ultimo_comentario_manual(ordenados, ate=None),
            chamada=chamada,
        )

    autoproceso = _texto(passo_fechamento.get("etl_cAccion")) == ACAO_AUTOPROCESO
    monitor = (
        MONITOR_AUTOMATICO if autoproceso else _texto(passo_fechamento.get("ope_cnombre")) or None
    )

    return AnaliseTimeline(
        inicio=inicio,
        fechamento=passo_fechamento["quando"],
        fechado_por_autoproceso=autoproceso,
        monitor=monitor,
        situacao=_ultimo_comentario_manual(ordenados, ate=passo_fechamento["quando"]),
        chamada=chamada,
    )


def _ultimo_comentario_manual(
    ordenados: Sequence[Mapping[str, object]], *, ate: datetime | None
) -> str | None:
    ultimo = None
    for passo in ordenados:
        if _texto(passo.get("etl_cAccion")) != ACAO_COMENTARIO:
            continue
        if ate is not None and passo["quando"] is not None and passo["quando"] > ate:
            break
        observacao = _texto(passo.get("etl_cObservacion"))
        if observacao.startswith(PREFIXO_COMENTARIO_AUTOMATICO):
            continue
        if observacao:
            ultimo = observacao
    return ultimo


def resolucao_indica_arme(
    situacao: str | None, *, termos_arme: Sequence[str] = TERMOS_ARME_PADRAO
) -> bool:
    """True quando a resolução indica que o cliente armou — respeitando
    negação: "ainda não foi ativado" NÃO conta como armado (critério de
    aceite explícito)."""
    if not situacao:
        return False

    texto = _normalizar_para_busca(situacao)
    palavras = texto.split()

    for termo in termos_arme:
        termo_normalizado = _normalizar_para_busca(termo)
        posicao = texto.find(termo_normalizado)
        while posicao != -1:
            # índice (em palavras) de onde o termo começa
            indice_palavra = len(texto[:posicao].split())
            janela = palavras[max(indice_palavra - _JANELA_NEGACAO_PALAVRAS, 0) : indice_palavra]
            if not any(p in _NEGACOES for p in janela):
                return True
            posicao = texto.find(termo_normalizado, posicao + 1)
    return False


def prefixo_do_dia(data: datetime) -> str:
    return _DIAS_SEMANA[data.weekday()]


def processar_atendimento(
    *,
    data_evento: datetime | None,
    conta: str,
    cliente: str,
    evento: str,
    timeline: Sequence[Mapping[str, object]],
    incluir_automaticos: bool = False,
    incluir_abertos: bool = False,
    termos_arme: Sequence[str] = TERMOS_ARME_PADRAO,
) -> AtendimentoProcessado:
    """Aplica as regras A.3 completas a um evento + sua linha do tempo e
    devolve a linha pronta do relatório (incluída, descartada ou aberta)."""
    analise = analisar_timeline(timeline)

    situacao_base = analise.situacao or ""
    if data_evento is not None and situacao_base:
        situacao = f"{prefixo_do_dia(data_evento)}: {situacao_base}"
    else:
        situacao = situacao_base

    tempo = ""
    if analise.inicio is not None and analise.fechamento is not None:
        tempo = formatar_duracao_hms(analise.fechamento - analise.inicio)

    def _resultado(status: str, motivo: str | None = None) -> AtendimentoProcessado:
        return AtendimentoProcessado(
            data_evento=data_evento,
            conta=conta,
            cliente=cliente,
            evento=evento,
            situacao=situacao,
            tempo_atendimento=tempo,
            monitor=analise.monitor or "",
            status=status,
            motivo_descarte=motivo,
        )

    if analise.fechamento is None:
        if incluir_abertos:
            return _resultado(INCLUIDO)
        return _resultado(ABERTO, "Evento ainda em aberto (sem fechamento)")

    if analise.fechado_por_autoproceso and not incluir_automaticos:
        return _resultado(
            DESCARTADO, "Fechamento automático (Autoproceso/CLO) — cliente armou"
        )

    if resolucao_indica_arme(analise.situacao, termos_arme=termos_arme):
        return _resultado(DESCARTADO, "Resolução indica que o cliente armou")

    return _resultado(INCLUIDO)
