"""Lojas sem arme — desliga o aviso de "não armou", sem cegar a conta.

**O que mudou em relação ao mecanismo anterior.** A primeira versão
colocava a conta "em teste", e isso calava a conta inteira: a falha de
arme, sim, mas também o **disparo**. Uma loja em teste com alguém dentro
não gerava nada. Aqui se mexe só no campo `tol_nnyc` da tolerância, que
governa exclusivamente o aviso de "não fechou ainda" — o BUR continua
chegando normalmente. É toda a razão deste módulo existir no lugar do
outro.

**E o que isso cobra em troca.** O teste tinha uma janela que expirava
sozinha: esquecer de desfazer não era possível. Este campo **fica
desligado até alguém religar**. A segurança deixa de ser o relógio da
plataforma e passa a ser o ciclo semanal:

- as contas da lista nova que ainda estão ligadas → **desligar**;
- as que estavam desligadas e saíram da lista → **religar**, restaurando
  o valor que cada uma tinha.

Quem não rodar a semana seguinte deixa lojas sem supervisão de arme por
tempo indeterminado. Por isso a tela mostra há quantos dias cada conta
está desligada, e destaca o que passou de uma semana: sem expiração
automática, esse contador é o único sintoma.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from app.domain import aviso_arme as dom
from app.domain import disparos_geral as dom_disp
from app.extensions import db
from app.integrations.softguard_client import SoftGuardClient, SoftGuardError
from app.models.aviso_arme import AvisoArmeDesligado
from app.services import audit_service
from app.services.collector import credenciais_softguard

logger = logging.getLogger("aviso_arme")

# Pausa entre gravações. O lote é de dezenas de contas, não de milhares;
# a pausa existe para não martelar o portal, não para ser rápida.
PAUSA_SEGUNDOS = 0.2

# Acima disso a tela destaca: sem janela que expira sozinha, uma conta
# desligada há mais de uma semana quer dizer que a lista parou de rodar.
DIAS_PARA_ALERTAR = 8


class AvisoArmeError(Exception):
    """Não deu para montar ou aplicar o lote."""


def _criar_cliente(config) -> SoftGuardClient:
    return SoftGuardClient(credenciais_softguard(config))


def contas_do_super_nosso(linhas_contas) -> tuple[list[dom.ContaAlvo], list[dom.ContaAlvo]]:
    """`(elegíveis, barradas)` — só Super Nosso e Apoio, sem tesouraria.

    O recorte por grupo é a classificação de
    `disparos_geral.grupo_do_cliente`, reaproveitada inteira — e aqui ele
    não é cosmético, é contenção: um número de filial solto ("530")
    casaria com qualquer conta da base que tivesse esse número no nome.
    Limitando o universo ao grupo que manda a lista, um erro de digitação
    não alcança a padaria da esquina.

    A **tesouraria é barrada à parte**, e devolvida numa lista própria em
    vez de sumir: exclusão silenciosa é indistinguível de esquecimento, e
    quem confere precisa ver que ela foi deixada de fora de propósito."""
    elegiveis: list[dom.ContaAlvo] = []
    barradas: list[dom.ContaAlvo] = []
    for linha in linhas_contas:
        nome = str(linha.get("cue_cnombre") or "").strip()
        cue_iid = linha.get("cue_iid")
        if not nome or cue_iid in (None, ""):
            continue
        if dom_disp.grupo_do_cliente(nome) != dom_disp.GRUPO_SUPER_NOSSO:
            continue
        alvo = dom.ContaAlvo(
            cue_iid=str(cue_iid),
            numero=str(linha.get("cue_ncuenta") or "").strip(),
            nome=nome,
        )
        (barradas if dom.nunca_desligar(nome) else elegiveis).append(alvo)
    return elegiveis, barradas


def desligadas_agora() -> list[AvisoArmeDesligado]:
    """As contas que estão sem o aviso neste momento."""
    return (
        AvisoArmeDesligado.query.filter_by(ativo=True)
        .order_by(AvisoArmeDesligado.desligado_em)
        .all()
    )


def preparar(mensagem: str, *, config, softguard_client=None) -> dict:
    """Lê a mensagem e devolve o que SERIA feito. Não escreve nada."""
    filiais = dom.extrair_filiais(mensagem)
    if not filiais:
        raise AvisoArmeError(
            "Não achei nenhum número de filial na mensagem. Cole o texto que o "
            "Super Nosso enviou, com os números das lojas."
        )

    client = softguard_client or _criar_cliente(config)
    try:
        linhas = client.listar_todas_contas()
    except SoftGuardError as exc:
        logger.exception("Aviso de arme: falha ao carregar as contas.")
        raise AvisoArmeError(
            f"Não foi possível carregar as contas da PowerCentral: {exc}"
        ) from exc

    alvos, barradas = contas_do_super_nosso(linhas)
    casamentos = dom.casar_filiais(filiais, alvos)
    casadas = [c.conta for c in casamentos if c.encontrada]

    ledger = {linha.cue_iid: linha for linha in desligadas_agora()}
    diferenca = dom.diferenca_da_semana(casadas, ledger)

    return {
        "desligar": list(diferenca.desligar),
        "ja_desligadas": list(diferenca.ja_desligadas),
        # A linha inteira do ledger, não só o id: a tela mostra o nome e
        # há quantos dias está desligada.
        "religar": [ledger[i] for i in diferenca.religar],
        "ambiguos": [c for c in casamentos if c.ambigua],
        "nao_encontrados": [
            c for c in casamentos if not c.encontrada and not c.ambigua
        ],
        "barradas": barradas,
        "elegiveis": len(alvos),
    }


def _desligar_uma(client, alvo: dom.ContaAlvo, *, user=None) -> None:
    """Lê a tolerância, GRAVA O LEDGER, e só então desliga.

    A ordem importa: o ledger antes do PUT. Se o processo morrer no meio,
    sobra uma linha dizendo "esta conta deveria estar desligada" — que se
    confere e se corrige — em vez de uma conta desligada que ninguém sabe
    que existe, e cujo valor original se perdeu para sempre."""
    tolerancia = client.ler_tolerancia(alvo.cue_iid)
    original = int(tolerancia["tol_nnyc"])

    linha = AvisoArmeDesligado(
        cue_iid=alvo.cue_iid,
        conta=alvo.numero[:16],
        nome=alvo.nome[:200],
        nnyc_original=original,
        desligado_em=datetime.now(timezone.utc),
        desligado_por_user_id=getattr(user, "id", None),
        ativo=True,
    )
    db.session.add(linha)
    db.session.flush()

    try:
        client.set_nao_armado(alvo.cue_iid, gerar=False)
    except Exception:
        # O PUT falhou: a conta continua ligada, então a linha do ledger
        # mentiria. Some com ela — o inverso (ledger sem conta desligada)
        # é inofensivo, a conta só não entrou no lote.
        db.session.delete(linha)
        db.session.flush()
        raise


def _religar_uma(client, linha: AvisoArmeDesligado, *, user=None) -> None:
    """Restaura o valor que a conta tinha e fecha a linha do ledger.

    O valor vem do ledger, nunca de uma constante: "tipicamente 2" não é
    "sempre 2", e religar com o número errado deixaria a conta com uma
    supervisão que ela nunca teve."""
    client.set_nao_armado(linha.cue_iid, gerar=True, original=linha.nnyc_original)
    linha.ativo = False
    linha.religado_em = datetime.now(timezone.utc)
    linha.religado_por_user_id = getattr(user, "id", None)
    db.session.flush()


def aplicar(
    cue_iids_desligar,
    cue_iids_religar,
    *,
    config,
    user=None,
    softguard_client=None,
) -> dict:
    """Executa os dois sentidos. **Escreve na plataforma.**

    Recebe os `cue_iid` que o admin confirmou na pré-visualização, e não
    a mensagem de novo: remontar a lista aqui abriria a porta para
    executar algo diferente do que foi conferido."""
    desligar = [str(i).strip() for i in cue_iids_desligar if str(i).strip()]
    religar = [str(i).strip() for i in cue_iids_religar if str(i).strip()]
    if not desligar and not religar:
        raise AvisoArmeError("Nenhuma conta confirmada.")

    client = softguard_client or _criar_cliente(config)

    # Barreira da tesouraria na beira da escrita, relendo o cadastro. A
    # primeira (o universo elegível) depende de o lote ter vindo de uma
    # pré-visualização íntegra; esta não depende de nada.
    protegidas = _tesourarias_por_iid(client)
    bloqueadas = [i for i in desligar if i in protegidas]
    desligar = [i for i in desligar if i not in protegidas]
    if bloqueadas:
        logger.warning("Aviso de arme: tesouraria barrada: %s", bloqueadas)

    elegiveis, _ = contas_do_super_nosso(client.listar_todas_contas())
    por_iid = {c.cue_iid: c for c in elegiveis}
    ledger = {linha.cue_iid: linha for linha in desligadas_agora()}

    desligadas: list[str] = []
    religadas: list[str] = []
    falhas: list[dict] = []

    total = len(desligar) + len(religar)
    feitas = 0

    for cue_iid in desligar:
        alvo = por_iid.get(cue_iid)
        if alvo is None:
            falhas.append(
                {"cue_iid": cue_iid, "erro": "conta não está mais entre as elegíveis"}
            )
        elif cue_iid in ledger:
            # Já desligada: regravar perderia o `nnyc_original` para
            # sempre, trocando-o por 1. É o erro mais caro possível aqui.
            logger.info("Aviso de arme: %s já estava desligada.", cue_iid)
        else:
            try:
                _desligar_uma(client, alvo, user=user)
                desligadas.append(cue_iid)
            except Exception as exc:  # noqa: BLE001 — uma conta não derruba o lote
                logger.warning("Aviso de arme: falhou ao desligar %s: %s", cue_iid, exc)
                falhas.append({"cue_iid": cue_iid, "erro": str(exc)[:300]})
        feitas += 1
        if PAUSA_SEGUNDOS and feitas < total:
            time.sleep(PAUSA_SEGUNDOS)

    for cue_iid in religar:
        linha = ledger.get(cue_iid)
        if linha is None:
            falhas.append({"cue_iid": cue_iid, "erro": "não consta como desligada"})
        else:
            try:
                _religar_uma(client, linha, user=user)
                religadas.append(cue_iid)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Aviso de arme: falhou ao religar %s: %s", cue_iid, exc)
                falhas.append({"cue_iid": cue_iid, "erro": str(exc)[:300]})
        feitas += 1
        if PAUSA_SEGUNDOS and feitas < total:
            time.sleep(PAUSA_SEGUNDOS)

    audit_service.registrar(
        action="aviso_arme_lote",
        result="failure" if falhas else "success",
        user=user,
        details={
            "desligadas": len(desligadas),
            "religadas": len(religadas),
            "falhas": len(falhas),
            "bloqueadas": len(bloqueadas),
        },
    )
    logger.info(
        "Aviso de arme: %s desligada(s), %s religada(s), %s falha(s).",
        len(desligadas), len(religadas), len(falhas),
    )
    return {
        "desligadas": desligadas,
        "religadas": religadas,
        "bloqueadas": bloqueadas,
        "falhas": falhas,
    }


def _tesourarias_por_iid(client) -> set[str]:
    """Os `cue_iid` das tesourarias, lidos do cadastro na hora de gravar.

    Lido agora, e não aproveitado da pré-visualização, porque é
    exatamente o caso em que não se quer confiar no que veio de fora."""
    try:
        _, barradas = contas_do_super_nosso(client.listar_todas_contas())
    except Exception:  # noqa: BLE001
        logger.exception("Aviso de arme: não consegui reler as contas.")
        raise AvisoArmeError(
            "Não consegui reler as contas para conferir as tesourarias. "
            "Nada foi gravado — tente de novo."
        ) from None
    return {c.cue_iid for c in barradas}


__all__ = [
    "AvisoArmeError",
    "DIAS_PARA_ALERTAR",
    "aplicar",
    "contas_do_super_nosso",
    "desligadas_agora",
    "preparar",
]
