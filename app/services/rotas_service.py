"""Catálogo de visita preventiva — clientes base agrupados por bairro.

Só leitura nas plataformas: nada é escrito na PowerCentral nem na Auvo.

A parte difícil não é agrupar (isso é o domínio), é **saber em que bairro
cada cliente fica**. O endereço vem de até quatro lugares, nesta ordem:

1. **Auvo ao vivo** (API) — é o app que o técnico usa em campo.
2. **Planilha da Auvo** importada — o mesmo dado, num retrato datado.
3. **PowerCentral ao vivo** (API).
4. **Planilha da PowerCentral** importada — daqui sai a cidade de quem
   não casou com a Auvo.

A planilha existe porque o catálogo não pode depender de adivinhar nome
de campo de API: essa aposta já falhou uma vez neste módulo e custou uma
rodada inteira com zero resultado na tela. Com a planilha importada, o
catálogo funciona mesmo que a API mude o nome de tudo.

O casamento com a Auvo é por `AuvoDepara` (status OK) e, na falta, por
nome com corte alto. O de-para vem primeiro de propósito: ele foi
confirmado por uma pessoa, o nome é palpite calculado.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.domain import disparos_geral as dom_disp
from app.domain import endereco as dom_end
from app.domain import planilhas as dom_pl
from app.domain import rotas as dom
from app.extensions import db
from app.integrations.softguard_client import SoftGuardClient, SoftGuardError
from app.models.auvo import AuvoDepara
from app.models.rotas import RotasEndereco
from app.services import audit_service, auvo_service
from app.services.collector import credenciais_softguard

logger = logging.getLogger("rotas")

CAMPOS_NOME_AUVO = ("description", "name", "customerDescription", "nome")
# Nomes tentados para o endereço nas APIs. A lista é um atalho, não a
# garantia: se nenhum bater, `_endereco_do_registro` procura pela forma.
CAMPOS_ENDERECO = ("address", "endereco", "endereço", "fullAddress", "logradouro")
CAMPOS_CIDADE = ("city", "cidade", "cityName", "localidade", "municipio")

FONTE_AUVO = "auvo"
FONTE_POWER = "power"


class RotasError(Exception):
    """Não deu para montar o catálogo (a PowerCentral está fora)."""


def _primeiro(linha, campos, padrao=""):
    if not isinstance(linha, dict):
        return padrao
    normalizados = {str(k).strip().lower(): v for k, v in linha.items()}
    for campo in campos:
        valor = normalizados.get(campo.lower())
        if valor not in (None, ""):
            return valor
    return padrao


def _endereco_do_registro(registro) -> dom_end.Endereco:
    """Acha o endereço num registro de API **sem depender do nome do
    campo**.

    Mesmo princípio da detecção de coordenada, e pelo mesmo motivo: a
    versão que chutava `cue_clocalizacion` devolveu 105 contas sem nada,
    em silêncio. Primeiro tenta os nomes conhecidos; se nenhum vier,
    varre os campos de texto e fica com o que **se prova** endereço, ou
    seja, o que tem UF ou CEP reconhecíveis. Essa exigência é o que
    impede um nome de cliente ou uma observação de passar por endereço."""
    if not isinstance(registro, dict):
        return dom_end.Endereco()

    nomeado = dom_end.ler(_primeiro(registro, CAMPOS_ENDERECO))
    if nomeado.bairro or nomeado.cidade:
        return nomeado

    melhor = dom_end.Endereco()
    for valor in registro.values():
        if not isinstance(valor, str) or len(valor) < 8:
            continue
        lido = dom_end.ler(valor)
        if not (lido.uf or lido.cep):
            continue
        if (lido.bairro, lido.cidade).count(None) < (melhor.bairro, melhor.cidade).count(None):
            melhor = lido
    return melhor


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
    casamento ainda não confirmado por humano: usá-lo aqui colocaria o
    cliente no bairro de outro."""
    return {
        str(linha.conta_power).strip().lstrip("0"): str(linha.id_auvo)
        for linha in AuvoDepara.query.filter_by(status="OK").all()
        if linha.id_auvo is not None
    }


# ----------------------------------------------------------------------
# Importação das planilhas
# ----------------------------------------------------------------------


def importar_planilha(conteudo: bytes, *, user=None) -> dict:
    """Importa o export da Auvo ou o relatório da PowerCentral.

    A fonte é detectada pelo conteúdo, não pela extensão — o relatório da
    PowerCentral se chama `.xls` e por dentro é HTML, e fazer a pessoa
    acertar qual é qual seria passar para ela um problema que os dois
    primeiros bytes do arquivo resolvem.

    **A importação substitui inteira a fonte que ela traz.** A planilha é
    o retrato completo daquele lado; misturar com o lote anterior
    deixaria no sistema o endereço de um cliente que já mudou, sem
    ninguém notar."""
    fonte = dom_pl.detectar(conteudo)
    if fonte == FONTE_AUVO:
        linhas = dom_pl.ler_planilha_auvo(conteudo)
    else:
        linhas = dom_pl.ler_planilha_power(conteudo)

    RotasEndereco.query.filter_by(fonte=fonte).delete(synchronize_session=False)

    agora = datetime.now(timezone.utc)
    salvos = com_bairro = com_cidade = 0
    for linha in linhas:
        endereco = dom_end.ler(linha.endereco)
        cidade = endereco.cidade or linha.cidade
        if not (endereco.bairro or cidade):
            continue
        db.session.add(
            RotasEndereco(
                fonte=fonte,
                conta_power=linha.conta or None,
                id_auvo=linha.id_auvo,
                nome=linha.nome[:200],
                nome_norm=dom.normalizar(linha.nome)[:200],
                bairro=(endereco.bairro or "")[:120],
                cidade=(cidade or "")[:120],
                uf=(endereco.uf or "")[:2],
                cep=(endereco.cep or "")[:12],
                endereco_bruto=linha.endereco or "",
                importado_em=agora,
                importado_por_user_id=getattr(user, "id", None),
            )
        )
        salvos += 1
        com_bairro += 1 if endereco.bairro else 0
        com_cidade += 1 if cidade else 0

    db.session.flush()
    resumo = {
        "fonte": fonte,
        "lidas": len(linhas),
        "salvas": salvos,
        "com_bairro": com_bairro,
        "com_cidade": com_cidade,
    }
    audit_service.registrar(
        action="rotas_planilha_importada", result="success", user=user, details=resumo
    )
    logger.info("Rotas: planilha %s importada — %s", fonte, resumo)
    return resumo


def _enderecos_importados() -> dict:
    """Os três índices de busca do que foi importado: conta, id Auvo e
    nome normalizado."""
    por_conta: dict[str, RotasEndereco] = {}
    por_id_auvo: dict[str, RotasEndereco] = {}
    por_nome: dict[str, RotasEndereco] = {}
    for linha in RotasEndereco.query.all():
        if linha.conta_power:
            por_conta[linha.conta_power.lstrip("0")] = linha
        if linha.id_auvo is not None:
            por_id_auvo[str(linha.id_auvo)] = linha
        if linha.nome_norm and linha.bairro:
            # Só entra no índice por nome quem tem bairro: o casamento por
            # nome é o mais frágil dos três, e usá-lo para trazer apenas a
            # cidade não compensaria o risco de pegar o cliente errado.
            por_nome.setdefault(linha.nome_norm, linha)
    return {"conta": por_conta, "id_auvo": por_id_auvo, "nome": por_nome}


def resumo_importacoes() -> list[dict]:
    """O que já foi importado, para a tela dizer de quando é o dado."""
    resumo = []
    for fonte, rotulo in ((FONTE_AUVO, "Auvo"), (FONTE_POWER, "PowerCentral")):
        linhas = RotasEndereco.query.filter_by(fonte=fonte).all()
        if not linhas:
            continue
        resumo.append(
            {
                "fonte": rotulo,
                "linhas": len(linhas),
                "com_bairro": sum(1 for linha in linhas if linha.bairro),
                "importado_em": max(linha.importado_em for linha in linhas),
            }
        )
    return resumo


# ----------------------------------------------------------------------
# Montagem do catálogo
# ----------------------------------------------------------------------


def montar_catalogo(*, config, user=None) -> dict:
    """Devolve `{"regioes": [...], "resumo": {...}}`.

    Falhar ao falar com a Auvo **não** cancela tudo: sobram a planilha
    importada e a PowerCentral. Entregar parte é melhor que não entregar
    nada — e o resumo diz de onde veio cada endereço."""
    client = SoftGuardClient(credenciais_softguard(config))
    try:
        linhas_contas = client.listar_todas_contas()
    except SoftGuardError as exc:
        logger.exception("Rotas: falha ao carregar as contas.")
        raise RotasError(
            f"Não foi possível carregar as contas da PowerCentral: {exc}"
        ) from exc

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
            logger.warning("Rotas: sem endereços da Auvo (%s).", exc)

    por_id = _mapa_auvo_por_id(clientes_auvo)
    depara = _depara_por_conta()
    nomes_auvo = {
        dom.normalizar(str(_primeiro(c, CAMPOS_NOME_AUVO))): c for c in clientes_auvo
    }
    importados = _enderecos_importados()

    clientes: list[dom.ClienteBase] = []
    contagem_fontes: dict[str, int] = {}

    for linha in base:
        conta = str(linha.get("cue_ncuenta") or "").strip()
        nome = str(linha.get("cue_cnombre") or "").strip()
        chave_conta = conta.lstrip("0")
        id_auvo = depara.get(chave_conta, "")

        bairro = cidade = fonte = ""

        # 1. Auvo ao vivo
        cliente = por_id.get(id_auvo)
        if cliente is None and nomes_auvo:
            casado = dom.melhor_nome(nome, list(nomes_auvo))
            cliente = nomes_auvo.get(casado) if casado else None
        if cliente is not None:
            lido = _endereco_do_registro(cliente)
            if lido.bairro or lido.cidade:
                bairro, cidade, fonte = lido.bairro or "", lido.cidade or "", dom.FONTE_AUVO

        # 2. Planilha da Auvo (por de-para, depois por nome)
        if not bairro:
            importado = importados["id_auvo"].get(id_auvo) or importados["nome"].get(
                dom.normalizar(nome)
            )
            if importado is None and importados["nome"]:
                casado = dom.melhor_nome(nome, list(importados["nome"]))
                importado = importados["nome"].get(casado) if casado else None
            if importado is not None and importado.bairro:
                bairro = importado.bairro
                cidade = cidade or importado.cidade
                fonte = dom.FONTE_AUVO_PLANILHA

        # 3. PowerCentral ao vivo — normalmente só a cidade
        if not cidade:
            lido = _endereco_do_registro(linha)
            cidade = lido.cidade or str(_primeiro(linha, CAMPOS_CIDADE)).strip()
            if cidade and not fonte:
                fonte = dom.FONTE_POWER
            if not bairro and lido.bairro:
                bairro, fonte = lido.bairro, dom.FONTE_POWER

        # 4. Planilha da PowerCentral
        if not cidade:
            importado = importados["conta"].get(chave_conta)
            if importado is not None:
                cidade = importado.cidade
                bairro = bairro or importado.bairro
                fonte = fonte or dom.FONTE_POWER_PLANILHA

        clientes.append(
            dom.ClienteBase(
                conta=conta, nome=nome, bairro=bairro, cidade=cidade, fonte=fonte
            )
        )
        if fonte:
            contagem_fontes[fonte] = contagem_fontes.get(fonte, 0) + 1

    regioes = dom.agrupar_por_regiao(clientes)
    com_bairro = sum(1 for c in clientes if c.bairro)
    resumo = {
        "base": len(base),
        "com_bairro": com_bairro,
        "sem_bairro": len(clientes) - com_bairro,
        "sem_regiao": sum(1 for c in clientes if not c.bairro and not c.cidade),
        "regioes": sum(1 for r in regioes if r.tem_bairro),
        "fontes": contagem_fontes,
        "erro_auvo": erro_auvo,
        "auvo_clientes": len(clientes_auvo),
        "importacoes": resumo_importacoes(),
    }

    audit_service.registrar(
        action="rotas_catalogo_gerado",
        result="success",
        user=user,
        details={
            "base": resumo["base"],
            "com_bairro": resumo["com_bairro"],
            "regioes": resumo["regioes"],
        },
    )
    return {"regioes": regioes, "resumo": resumo}
