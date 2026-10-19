"""Contas em teste em lote — o módulo que SUPRIME ALARME.

Colocar uma conta "em teste" faz a central parar de tratar a falha de
arme dela. É o efeito desejado para a loja que não vai armar naquela
semana, e é um buraco de segurança para qualquer outra. Daí a forma:

1. **Pré-visualização sempre**, e ela não escreve nada. A lista vem de
   uma mensagem escrita por gente, e conferir conta por conta antes de
   gravar é o passo que separa "a lista da semana" de "silenciar a loja
   errada".
2. **Confirmação explícita do admin** para gravar.
3. **Janela de tempo obrigatória.** O estado expira sozinho, e é isso —
   não o cuidado de quem opera — que impede uma conta de ficar
   silenciada para sempre. Por isso não existe passo de remover: a
   semana anterior já venceu quando a próxima lista chega.
4. **Falha por conta isolada**, com o motivo preservado. Metade do lote
   aplicado e dito às claras é melhor que um erro genérico que não diz
   quais entraram.

O disparo é humano, quando a lista chega — não um agendamento cego, que
colocaria contas em teste numa semana em que ninguém mandou lista.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from app.domain import contas_teste as dom
from app.domain import disparos_geral as dom_disp
from app.domain.dates import FUSO_HORARIO
from app.integrations.softguard_client import (
    SoftGuardClient,
    SoftGuardError,
    TIPO_EM_TESTE,
)
from app.services import audit_service, settings_service
from app.services.collector import credenciais_softguard

logger = logging.getLogger("contas_teste")

# Pausa entre gravações. O lote é de dezenas de contas, não de milhares;
# a pausa existe para não martelar o portal, não para ser rápida.
PAUSA_SEGUNDOS = 0.2


class ContasTesteError(Exception):
    """Não deu para montar ou aplicar o lote."""


def _criar_cliente(config) -> SoftGuardClient:
    return SoftGuardClient(credenciais_softguard(config))


def contas_do_super_nosso(linhas_contas) -> list[dom.ContaAlvo]:
    """As contas elegíveis: só Super Nosso e Apoio.

    O recorte é a classificação de `disparos_geral.grupo_do_cliente`,
    reaproveitada inteira — e aqui ele não é cosmético, é contenção: um
    número de filial solto ("530") casaria com qualquer conta da base que
    tivesse esse número no nome. Limitando o universo ao grupo que manda
    a lista, um erro de digitação não alcança a padaria da esquina."""
    alvos = []
    for linha in linhas_contas:
        nome = str(linha.get("cue_cnombre") or "").strip()
        cue_iid = linha.get("cue_iid")
        if not nome or cue_iid in (None, ""):
            continue
        if dom_disp.grupo_do_cliente(nome) != dom_disp.GRUPO_SUPER_NOSSO:
            continue
        alvos.append(
            dom.ContaAlvo(
                cue_iid=str(cue_iid),
                numero=str(linha.get("cue_ncuenta") or "").strip(),
                nome=nome,
            )
        )
    return alvos


def preparar(
    mensagem: str, *, config, dias: int | None = None, softguard_client=None
) -> dict:
    """Lê a mensagem e devolve o que SERIA feito. Não escreve nada.

    Devolve `{"casados", "nao_encontrados", "ambiguos", "inicio", "fim",
    "dias"}` — as três listas separadas porque cada uma pede uma ação
    diferente de quem confere."""
    dias = dias or settings_service.get_teste_duracao_dias()
    filiais = dom.extrair_filiais(mensagem)
    if not filiais:
        raise ContasTesteError(
            "Não achei nenhum número de filial na mensagem. Cole o texto que o "
            "Super Nosso enviou, com os números das lojas."
        )

    client = softguard_client or _criar_cliente(config)
    try:
        linhas = client.listar_todas_contas()
    except SoftGuardError as exc:
        logger.exception("Contas em teste: falha ao carregar as contas.")
        raise ContasTesteError(
            f"Não foi possível carregar as contas da PowerCentral: {exc}"
        ) from exc

    alvos = contas_do_super_nosso(linhas)
    casamentos = dom.casar_filiais(filiais, alvos)

    inicio = datetime.now(FUSO_HORARIO).replace(microsecond=0)
    _, fim = dom.janela(inicio, dias)

    return {
        "casados": [c for c in casamentos if c.encontrada],
        "ambiguos": [c for c in casamentos if c.ambigua],
        "nao_encontrados": [
            c for c in casamentos if not c.encontrada and not c.ambigua
        ],
        "inicio": inicio,
        "fim": fim,
        "dias": dias,
        "elegiveis": len(alvos),
    }


def aplicar(
    cue_iids,
    *,
    config,
    dias: int | None = None,
    nota: str | None = None,
    user=None,
    softguard_client=None,
) -> dict:
    """Coloca em teste as contas confirmadas. **Escreve na plataforma.**

    Recebe os `cue_iid` que o admin confirmou na pré-visualização, e não
    a mensagem de novo: remontar a lista aqui abriria a porta para
    executar algo diferente do que foi conferido."""
    dias = dias or settings_service.get_teste_duracao_dias()
    nota = nota if nota is not None else settings_service.get_teste_nota_padrao()
    tipo = settings_service.get_teste_tipo()

    alvos = [str(i).strip() for i in cue_iids if str(i).strip()]
    if not alvos:
        raise ContasTesteError("Nenhuma conta confirmada para colocar em teste.")

    client = softguard_client or _criar_cliente(config)
    inicio = datetime.now(FUSO_HORARIO).replace(microsecond=0)
    _, fim = dom.janela(inicio, dias)

    aplicados: list[str] = []
    falhas: list[dict] = []
    for indice, cue_iid in enumerate(alvos):
        try:
            client.colocar_em_teste(
                cue_iid, inicio=inicio, dias=dias, nota=nota, tipo=tipo
            )
            aplicados.append(cue_iid)
        except Exception as exc:  # noqa: BLE001 — uma conta não derruba o lote
            logger.warning("Contas em teste: falhou em %s: %s", cue_iid, exc)
            falhas.append({"cue_iid": cue_iid, "erro": str(exc)[:300]})
        if PAUSA_SEGUNDOS and indice < len(alvos) - 1:
            time.sleep(PAUSA_SEGUNDOS)

    audit_service.registrar(
        action="contas_teste_lote",
        result="failure" if falhas else "success",
        user=user,
        details={
            "pedidas": len(alvos),
            "aplicadas": len(aplicados),
            "falhas": len(falhas),
            "dias": dias,
            "tipo": tipo,
            "inicio": inicio.isoformat(),
            "fim": fim.isoformat(),
        },
    )
    logger.info(
        "Contas em teste: %s aplicada(s), %s falha(s), até %s.",
        len(aplicados), len(falhas), fim,
    )
    return {
        "aplicados": aplicados,
        "falhas": falhas,
        "inicio": inicio,
        "fim": fim,
        "dias": dias,
        "tipo": tipo,
    }


__all__ = [
    "ContasTesteError",
    "TIPO_EM_TESTE",
    "aplicar",
    "contas_do_super_nosso",
    "preparar",
]
