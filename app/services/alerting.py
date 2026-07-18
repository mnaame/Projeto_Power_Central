from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import Sequence

from app.domain.classification import SEM_COMUNICACAO, ContaClassificada
from app.domain.diffing import contas_sem_comunicacao, detectar_mudanca
from app.extensions import db
from app.integrations.telegram_client import TelegramClient, TelegramError
from app.models.cycle import AlertSent, CollectionCycle

logger = logging.getLogger("collector")

_SEM_DATA = datetime(9999, 1, 1, tzinfo=timezone.utc)


def _formatar_duracao(desde: datetime | None, agora: datetime) -> str:
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


def _formatar_data(data: datetime | None) -> str:
    if data is None:
        return "sem registro"
    return data.strftime("%d/%m/%Y %H:%M")


def _linha_conta(conta: ContaClassificada, *, agora: datetime) -> str:
    nome = html.escape(conta.account_name or "sem nome")
    numero = html.escape(conta.account_number)
    return (
        f"<b>{numero}</b> — {nome}\n"
        f"Em falha desde: {_formatar_data(conta.tst_failure_since)} "
        f"({_formatar_duracao(conta.tst_failure_since, agora)})\n"
        f"Último evento: {html.escape(conta.last_event_code or 'nenhum')} em "
        f"{_formatar_data(conta.last_event_at)} "
        f"({_formatar_duracao(conta.last_event_at, agora)})"
    )


def _chave_ordenacao(conta: ContaClassificada) -> tuple[bool, datetime]:
    data = conta.tst_failure_since
    return (data is None, data or _SEM_DATA)


def montar_relatorio_sem_comunicacao(
    contas: Sequence[ContaClassificada], *, agora: datetime
) -> str:
    """Relatório ordenado do mais antigo em falha para o mais recente
    (regra 5), somente contas SEM_COMUNICACAO — falsos positivos ficam de
    fora por padrão (regra 6.3)."""
    sem_comunicacao = [c for c in contas if c.classification == SEM_COMUNICACAO]
    ordenadas = sorted(sem_comunicacao, key=_chave_ordenacao)

    cabecalho = f"<b>Clientes sem comunicação real ({len(ordenadas)})</b>"
    if not ordenadas:
        return cabecalho + "\nNenhum cliente sem comunicação no momento."

    linhas = [_linha_conta(conta, agora=agora) for conta in ordenadas]
    return cabecalho + "\n\n" + "\n\n".join(linhas)


def montar_mensagem_normalizacao(agora: datetime) -> str:
    return (
        "<b>Normalizado</b>\n"
        "Todas as contas voltaram a comunicar. Nenhum cliente sem comunicação"
        f" às {agora.strftime('%d/%m/%Y %H:%M')}."
    )


def registrar_e_enviar_alerta(
    telegram_client: TelegramClient | None,
    *,
    cycle_id: int | None,
    tipo: str,
    texto: str,
) -> AlertSent:
    """Envia `texto` pelo Telegram (se configurado) e grava o resultado em
    AlertSent — histórico auditável de todo alerta, enviado ou não."""
    alerta = AlertSent(cycle_id=cycle_id, message_type=tipo, success=False)

    if telegram_client is None:
        logger.warning("Telegram não configurado; alerta (%s) não enviado.", tipo)
    else:
        try:
            ids = telegram_client.enviar_mensagem(texto)
            alerta.success = True
            alerta.telegram_message_id = ",".join(ids)
        except TelegramError:
            logger.exception("Falha ao enviar alerta (%s) ao Telegram.", tipo)

    db.session.add(alerta)
    return alerta


def processar_alertas(
    *,
    cycle: CollectionCycle,
    contas_atuais: Sequence[ContaClassificada],
    contas_anteriores_sem_comunicacao: Sequence[str],
    telegram_client: TelegramClient | None,
    agora: datetime,
) -> AlertSent | None:
    """Aplica a regra 6.4: alerta só quando o conjunto de contas sem
    comunicação muda (entrada, saída ou normalização). Sem mudança,
    retorna None e não grava/envia nada."""
    atuais_sem_comunicacao = sorted(contas_sem_comunicacao(contas_atuais))
    mudanca = detectar_mudanca(contas_anteriores_sem_comunicacao, atuais_sem_comunicacao)

    if not mudanca.mudou:
        return None

    texto = (
        montar_mensagem_normalizacao(agora)
        if mudanca.tipo == "normalizacao"
        else montar_relatorio_sem_comunicacao(contas_atuais, agora=agora)
    )

    alerta = registrar_e_enviar_alerta(
        telegram_client, cycle_id=cycle.id, tipo=mudanca.tipo, texto=texto
    )
    alerta.accounts_added = mudanca.contas_adicionadas
    alerta.accounts_removed = mudanca.contas_removidas
    return alerta
