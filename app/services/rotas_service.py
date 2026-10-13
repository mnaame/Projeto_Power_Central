"""Rotas de visita preventiva — junta PowerCentral, Auvo e o de-para.

Só leitura: nada é escrito em nenhuma das duas plataformas.

A parte difícil não é agrupar (isso é o domínio), é **saber onde cada
cliente fica**. A coordenada vem de duas fontes com confiabilidades
diferentes:

1. **Auvo** é a principal. É o app que o técnico usa em campo, então a
   coordenada dali foi conferida por alguém que esteve no local.
2. **PowerCentral** é a reserva, e entra só com a região validada — parte
   das coordenadas de lá aponta para outro estado.

O casamento entre as duas bases é por `AuvoDepara` (status OK) e, na
falta, por nome com corte alto. O de-para vem primeiro de propósito: ele
foi confirmado por uma pessoa, o nome é palpite calculado.
"""

from __future__ import annotations

import logging

from app.domain import disparos_geral as dom_disp
from app.domain import rotas as dom
from app.integrations.softguard_client import SoftGuardClient, SoftGuardError
from app.models.auvo import AuvoDepara
from app.services import audit_service, auvo_service
from app.services.collector import credenciais_softguard

logger = logging.getLogger("rotas")

CAMPOS_NOME_AUVO = ("description", "name", "customerDescription", "nome")
CAMPOS_CIDADE = ("city", "cidade", "cityName")

# Nenhuma lista de campos de coordenada aqui, de propósito: a primeira
# versão procurava a localização da conta por nome de campo
# (`cue_clocalizacion`), errou o nome e devolveu 105 contas sem
# coordenada — zero, sem um único erro na tela. Quem acha a coordenada
# agora é `dom.coordenada_do_registro`, que a reconhece pela forma (dois
# decimais dentro da caixa da região) em vez do nome.


class RotasError(Exception):
    """Não deu para montar as rotas (uma das duas plataformas fora)."""


def _primeiro(linha, campos, padrao=""):
    for campo in campos:
        valor = linha.get(campo)
        if valor not in (None, ""):
            return valor
    return padrao


def _motivo_sem_coordenada(cliente, *, achou_auvo: bool) -> str:
    """O motivo é a instrução de conserto: esta lista é a fila de trabalho
    do cadastro, e "sem coordenada" sozinho não diz onde mexer."""
    if not achou_auvo:
        return "Auvo indisponível e sem localização válida na PowerCentral"
    if cliente is None:
        return "Não casou com nenhum cliente da Auvo e sem localização válida na PowerCentral"
    return "Cliente da Auvo sem lat/long (ou fora da região) e sem localização válida na PowerCentral"


def _contas_base(linhas_contas) -> list[dict]:
    """Base = tudo que não é Villefort, Super Nosso/Apoio nem interno.

    A classificação por grupo é a de `disparos_geral.grupo_do_cliente`,
    reaproveitada inteira: ter duas definições de "quem é Villefort" no
    sistema seria o começo de dois números diferentes para a mesma
    pergunta."""
    base = []
    for linha in linhas_contas:
        nome = str(linha.get("cue_cnombre") or "").strip()
        if not nome or dom.e_interno(nome):
            continue
        if dom_disp.grupo_do_cliente(nome) != dom_disp.GRUPO_BASE:
            continue
        base.append(linha)
    return base


def _mapa_auvo_por_id(clientes) -> dict[str, dict]:
    return {str(c.get("id")): c for c in clientes if c.get("id") is not None}


def _depara_por_conta() -> dict[str, str]:
    """Conta -> id Auvo, só os confirmados (status OK). REVISAR é
    casamento ainda não confirmado por humano: usá-lo aqui mandaria o
    técnico para o endereço de outro cliente."""
    return {
        str(linha.conta_power).strip().lstrip("0"): str(linha.id_auvo)
        for linha in AuvoDepara.query.filter_by(status="OK").all()
        if linha.id_auvo is not None
    }


def montar_rotas(*, config, raio_km: float, user=None) -> dict:
    """Devolve `{"rotas": [...], "sem_coord": [...], "resumo": {...}}`.

    Falhar ao falar com a Auvo **não** cancela tudo: sem ela sobra a
    coordenada da PowerCentral, que cobre parte da base. Entregar metade
    é melhor que entregar nada — e o resumo diz de onde veio cada
    coordenada."""
    client = SoftGuardClient(credenciais_softguard(config))
    try:
        linhas_contas = client.listar_todas_contas()
    except SoftGuardError as exc:
        logger.exception("Rotas: falha ao carregar as contas.")
        raise RotasError(f"Não foi possível carregar as contas da PowerCentral: {exc}") from exc

    base = _contas_base(linhas_contas)

    clientes_auvo: list[dict] = []
    erro_auvo = ""
    cliente_auvo = auvo_service.criar_cliente(config)
    if cliente_auvo is None:
        erro_auvo = "Auvo não configurada (sem chave/token em Configurações)."
        logger.warning("Rotas: %s", erro_auvo)
    else:
        try:
            clientes_auvo = cliente_auvo.listar_clientes()
        except Exception as exc:  # noqa: BLE001 — a Auvo é fonte preferida, não obrigatória
            erro_auvo = str(exc)
            logger.warning("Rotas: sem coordenadas da Auvo (%s).", exc)

    por_id = _mapa_auvo_por_id(clientes_auvo)
    depara = _depara_por_conta()
    nomes_auvo = {
        dom.normalizar(str(_primeiro(c, CAMPOS_NOME_AUVO))): c for c in clientes_auvo
    }

    pontos: list[dom.PontoCliente] = []
    sem_coord: list[dict] = []
    casados = 0

    for linha in base:
        conta = str(linha.get("cue_ncuenta") or "").strip()
        nome = str(linha.get("cue_cnombre") or "").strip()
        cidade = str(_primeiro(linha, CAMPOS_CIDADE)).strip()

        cliente = por_id.get(depara.get(conta.lstrip("0"), ""))
        if cliente is None and nomes_auvo:
            casado = dom.melhor_nome(nome, list(nomes_auvo))
            cliente = nomes_auvo.get(casado) if casado else None

        casados += 1 if cliente else 0
        coordenada = dom.coordenada_do_registro(cliente) if cliente else None
        fonte = dom.FONTE_AUVO
        if coordenada is None:
            coordenada = dom.coordenada_do_registro(linha)
            fonte = dom.FONTE_POWER

        if coordenada is None:
            sem_coord.append(
                {
                    "conta": conta,
                    "nome": nome,
                    "cidade": cidade,
                    "motivo": _motivo_sem_coordenada(cliente, achou_auvo=bool(nomes_auvo)),
                }
            )
            continue

        lat, lon = coordenada
        pontos.append(
            dom.PontoCliente(
                conta=conta, nome=nome, cidade=cidade, lat=lat, lon=lon, fonte=fonte
            )
        )

    rotas = dom.agrupar(pontos, raio_km=raio_km)
    resumo = {
        "base": len(base),
        "com_coord": len(pontos),
        "sem_coord": len(sem_coord),
        "clusters": len(rotas),
        "raio_km": raio_km,
        "de_auvo": sum(1 for p in pontos if p.fonte == dom.FONTE_AUVO),
        "da_power": sum(1 for p in pontos if p.fonte == dom.FONTE_POWER),
        "erro_auvo": erro_auvo,
        # Diagnóstico do caminho da Auvo. Sem estes três, um "0 Auvo" na
        # tela não diz NADA: pode ser Auvo fora, pode ser nome que não
        # casou, pode ser cadastro sem lat/long. Com eles, dá para ver em
        # qual etapa a coordenada se perdeu.
        "auvo_clientes": len(clientes_auvo),
        "auvo_com_coord": sum(
            1 for c in clientes_auvo if dom.coordenada_do_registro(c) is not None
        ),
        "auvo_casados": casados,
    }

    audit_service.registrar(
        action="rotas_geradas",
        result="success",
        user=user,
        details={
            "base": resumo["base"],
            "com_coord": resumo["com_coord"],
            "clusters": resumo["clusters"],
            "raio_km": raio_km,
        },
    )
    return {"rotas": rotas, "sem_coord": sem_coord, "resumo": resumo}
