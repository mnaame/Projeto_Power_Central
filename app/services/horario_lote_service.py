"""Ajuste de horário em lote — varredura, backup, simulação e escrita.

**O módulo mais perigoso do sistema.** É o único que escreve no cadastro
da plataforma, e escreve em todas as contas. Um erro aqui não quebra uma
tela: desregula a supervisão da base inteira, e o estrago só aparece dias
depois, quando um "não abriu" deixar de ser disparado.

Daí as travas, em ordem de importância:

1. **Nada é gravado sem o lote estar preparado e persistido.** A
   varredura guarda o valor ANTES de cada linha; é dele que sai o backup
   e é contra ele que a idempotência compara.
2. **Simulação ligada por padrão.** Sair dela é decisão explícita do
   admin, em configuração.
3. **Aplica-se exatamente o que foi revisado.** O "aplicar" lê o lote
   salvo, nunca varre de novo — senão o admin confirmaria uma lista e
   executaria outra.
4. **Releitura antes de cada escrita.** Imediatamente antes de gravar uma
   conta, os horários dela são lidos de novo no portal: só grava onde o
   valor atual ainda é exatamente o `antes`. Se já está no `depois`,
   pula; se virou outra coisa, não toca e marca divergente.
5. **Falha isolada por linha**, com o motivo registrado.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from app.domain import horario_lote as dom
from app.extensions import db
from app.integrations.softguard_client import SoftGuardClient, SoftGuardError
from app.models.horario_lote import AjusteHorarioItem, AjusteHorarioLote
from app.services import audit_service, settings_service
from app.services.collector import credenciais_softguard

logger = logging.getLogger("horario_lote")


class HorarioLoteError(Exception):
    """Não deu nem para começar (portal fora, login recusado)."""


def _criar_cliente(config) -> SoftGuardClient:
    return SoftGuardClient(credenciais_softguard(config))


# ----------------------------------------------------------------------
# Preparação (só leitura)
# ----------------------------------------------------------------------


def preparar(*, config, user_id=None, softguard_client=None) -> AjusteHorarioLote:
    """Varre todas as contas, calcula o de→para e persiste o lote.

    Não grava nada no portal. Ao fim existe um lote `preparado` com uma
    linha por horário encontrado — o backup e a pré-visualização saem
    dele."""
    client = softguard_client or _criar_cliente(config)
    delta = settings_service.get_horario_lote_delta_min()
    pausa = settings_service.get_horario_lote_pausa_segundos()

    try:
        contas = client.listar_todas_contas()
    except SoftGuardError as exc:
        logger.exception("Ajuste de horário: falha ao carregar as contas.")
        raise HorarioLoteError(
            f"Não foi possível carregar as contas da PowerCentral: {exc}"
        ) from exc

    lote = AjusteHorarioLote(
        criado_por_user_id=user_id,
        delta_min=delta,
        simulacao=settings_service.horario_lote_simulacao(),
        status="preparado",
    )
    db.session.add(lote)
    db.session.flush()

    varridas = 0
    for linha_conta in contas:
        cue_iid = linha_conta.get("cue_iid") or linha_conta.get("Id")
        if cue_iid is None:
            continue
        conta = str(linha_conta.get("cue_ncuenta") or "").strip()
        nome = str(linha_conta.get("cue_cnombre") or "").strip()

        try:
            linhas = client.listar_horarios(cue_iid)
        except Exception as exc:  # noqa: BLE001 — uma conta não derruba a varredura
            logger.warning("Ajuste de horário: falha ao ler a conta %s: %s", conta, exc)
            continue

        varridas += 1
        for preparada in dom.preparar_linhas(
            linhas, conta=conta, nome=nome, delta_min=delta
        ):
            db.session.add(
                AjusteHorarioItem(
                    lote_id=lote.id,
                    horario_id=preparada.horario_id,
                    cue_iid=preparada.cue_iid or str(cue_iid),
                    conta=preparada.conta,
                    nome=preparada.nome,
                    dia_abertura=preparada.dia_abertura,
                    hora_abertura=preparada.hora_abertura,
                    dia_fechamento=preparada.dia_fechamento,
                    antes=preparada.antes,
                    depois=preparada.depois,
                    categoria=preparada.categoria,
                    # A categoria já é o destino final das linhas que não
                    # serão tocadas — elas nascem fechadas, não pendentes.
                    status={
                        dom.CATEGORIA_APLICAR: "pendente",
                        dom.CATEGORIA_MANUAL: "manual",
                        dom.CATEGORIA_INVALIDO: "invalido",
                    }[preparada.categoria],
                )
            )
        if pausa:
            time.sleep(pausa)

    lote.contas_varridas = varridas
    db.session.flush()
    return lote


def itens(lote: AjusteHorarioLote, *, categoria: str | None = None, status: str | None = None):
    query = lote.itens
    if categoria:
        query = query.filter(AjusteHorarioItem.categoria == categoria)
    if status:
        query = query.filter(AjusteHorarioItem.status == status)
    return query.order_by(AjusteHorarioItem.conta, AjusteHorarioItem.dia_fechamento).all()


def ultimo_lote() -> AjusteHorarioLote | None:
    return AjusteHorarioLote.query.order_by(AjusteHorarioLote.criado_em.desc()).first()


def resumo(lote: AjusteHorarioLote) -> dict:
    contagem = {
        status: lote.itens.filter(AjusteHorarioItem.status == status).count()
        for status in (
            "pendente", "aplicado", "simulado", "manual",
            "invalido", "ja_aplicado", "divergente", "erro",
        )
    }
    contagem["total"] = lote.itens.count()
    return contagem


# ----------------------------------------------------------------------
# Aplicação (escreve no portal)
# ----------------------------------------------------------------------


def _aplicar_item(
    item: AjusteHorarioItem, *, atuais: dict[str, dict], client, simular: bool
) -> str:
    """Decide e executa uma linha. Devolve o status final.

    A decisão vem da releitura (`atuais`), não do que estava no lote: o
    lote diz o que se QUERIA fazer, o portal diz o que PODE ser feito
    agora."""
    atual = atuais.get(str(item.horario_id))
    if atual is None:
        item.erro_mensagem = "Horário não existe mais no portal."
        return "divergente"

    valor_atual = str(atual.get("hor_choracierre") or "").strip()
    if valor_atual == item.depois:
        # Já está no destino: segunda execução, ou alguém ajustou à mão.
        # Em nenhum dos casos some mais uma hora.
        return "ja_aplicado"
    if valor_atual != item.antes:
        item.erro_mensagem = (
            f"No portal está {valor_atual!r}, e o lote foi preparado com {item.antes!r}."
        )
        return "divergente"

    if simular:
        return "simulado"

    try:
        client.atualizar_horario(
            dom.corpo_do_put(atual, novo_fechamento_hhmm=item.depois)
        )
    except Exception as exc:  # noqa: BLE001 — uma linha não derruba o lote
        logger.warning(
            "Ajuste de horário: falha ao gravar o horário %s (conta %s): %s",
            item.horario_id, item.conta, exc,
        )
        item.erro_mensagem = str(exc)
        return "erro"

    item.aplicado_em = datetime.now(timezone.utc)
    return "aplicado"


def aplicar(
    lote: AjusteHorarioLote,
    *,
    config,
    user,
    apenas_conta: str = "",
    softguard_client=None,
) -> dict:
    """Executa as linhas pendentes do lote.

    `apenas_conta` restringe a uma conta — é o teste obrigatório antes de
    soltar na base inteira. Respeita a simulação; em simulação nenhum PUT
    é enviado e os itens ficam `simulado` (continuam pendentes para a
    execução real)."""
    client = softguard_client or _criar_cliente(config)
    simular = lote.simulacao
    pausa = settings_service.get_horario_lote_pausa_segundos()

    pendentes = lote.itens.filter(AjusteHorarioItem.status == "pendente")
    if apenas_conta:
        pendentes = pendentes.filter(AjusteHorarioItem.conta == apenas_conta)
    pendentes = pendentes.order_by(AjusteHorarioItem.conta).all()

    lote.status = "aplicando"
    db.session.flush()

    contagem: dict[str, int] = {}
    por_conta: dict[str, list[AjusteHorarioItem]] = {}
    for item in pendentes:
        por_conta.setdefault(item.cue_iid, []).append(item)

    for cue_iid, do_grupo in por_conta.items():
        # UMA releitura por conta cobre todas as linhas dela: a proteção
        # continua por linha, sem pagar uma requisição por linha.
        try:
            atuais = {
                str(linha.get("Id")): linha for linha in client.listar_horarios(cue_iid)
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ajuste de horário: não reli a conta %s: %s", cue_iid, exc)
            for item in do_grupo:
                item.status = "erro"
                item.erro_mensagem = f"Não foi possível reler o horário atual: {exc}"
                contagem["erro"] = contagem.get("erro", 0) + 1
            db.session.flush()
            continue

        for item in do_grupo:
            status = _aplicar_item(item, atuais=atuais, client=client, simular=simular)
            item.status = status
            contagem[status] = contagem.get(status, 0) + 1
            if status == "aplicado":
                audit_service.registrar(
                    action="horario_lote_ajuste",
                    result="success",
                    user=user,
                    details={
                        "lote_id": lote.id,
                        "horario_id": item.horario_id,
                        "conta": item.conta,
                        "antes": item.antes,
                        "depois": item.depois,
                    },
                )
            db.session.flush()
            if pausa:
                time.sleep(pausa)

    aplicados = contagem.get("aplicado", 0)
    problemas = contagem.get("erro", 0) + contagem.get("divergente", 0)
    if simular:
        lote.status = "preparado"
    elif aplicados and not problemas:
        lote.status = "aplicado"
        lote.aplicado_em = datetime.now(timezone.utc)
    elif aplicados:
        lote.status = "parcial"
        lote.aplicado_em = datetime.now(timezone.utc)
    elif problemas:
        lote.status = "error"
    else:
        lote.status = "preparado"

    audit_service.registrar(
        action="horario_lote_execucao",
        result="success",
        user=user,
        details={
            "lote_id": lote.id,
            "simulacao": simular,
            "apenas_conta": apenas_conta or None,
            **contagem,
        },
    )
    db.session.flush()
    return contagem
