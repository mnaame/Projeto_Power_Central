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
from app.domain import geo
from app.domain import planilhas as dom_pl
from app.domain import rotas as dom
from app.extensions import db
from app.integrations.softguard_client import SoftGuardClient, SoftGuardError
from app.models.auvo import AuvoDepara
from app.models.rotas import (
    RotasBairroManual,
    RotasCiclo,
    RotasCicloCliente,
    RotasEndereco,
)
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
    salvos = com_bairro = com_cidade = com_coord = 0
    for linha in linhas:
        endereco = dom_end.ler(linha.endereco)
        cidade = endereco.cidade or linha.cidade
        # A Auvo manda lat e lon em campos separados; a PowerCentral manda
        # o par "lat,long" num campo só. Os dois caminhos passam pela
        # mesma validação de região.
        coordenada = geo.coordenada_valida(linha.lat, linha.lon) or geo.coordenada_de_texto(
            linha.lat
        )
        if not (endereco.bairro or cidade or coordenada):
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
                lat=coordenada[0] if coordenada else None,
                lon=coordenada[1] if coordenada else None,
                importado_em=agora,
                importado_por_user_id=getattr(user, "id", None),
            )
        )
        salvos += 1
        com_bairro += 1 if endereco.bairro else 0
        com_cidade += 1 if cidade else 0
        com_coord += 1 if coordenada else 0

    db.session.flush()
    resumo = {
        "fonte": fonte,
        "lidas": len(linhas),
        "salvas": salvos,
        "com_bairro": com_bairro,
        "com_cidade": com_cidade,
        "com_coordenada": com_coord,
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
                "com_coordenada": sum(1 for linha in linhas if linha.lat is not None),
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

    manuais = {linha.conta: linha for linha in RotasBairroManual.query.all()}

    clientes: list[dom.ClienteBase] = []
    contagem_fontes: dict[str, int] = {}

    for linha in base:
        conta = str(linha.get("cue_ncuenta") or "").strip()
        nome = str(linha.get("cue_cnombre") or "").strip()
        chave_conta = conta.lstrip("0")
        id_auvo = depara.get(chave_conta, "")

        bairro = cidade = fonte = ""
        coordenada = None

        # 1. Auvo ao vivo
        cliente = por_id.get(id_auvo)
        if cliente is None and nomes_auvo:
            casado = dom.melhor_nome(nome, list(nomes_auvo))
            cliente = nomes_auvo.get(casado) if casado else None
        if cliente is not None:
            lido = _endereco_do_registro(cliente)
            if lido.bairro or lido.cidade:
                bairro, cidade, fonte = lido.bairro or "", lido.cidade or "", dom.FONTE_AUVO
            coordenada = geo.coordenada_do_registro(cliente)

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
            if coordenada is None and importado is not None:
                coordenada = geo.coordenada_valida(importado.lat, importado.lon)

        # 3. PowerCentral ao vivo — normalmente só a cidade
        if coordenada is None:
            coordenada = geo.coordenada_do_registro(linha)
        if not cidade:
            lido = _endereco_do_registro(linha)
            cidade = lido.cidade or str(_primeiro(linha, CAMPOS_CIDADE)).strip()
            if cidade and not fonte:
                fonte = dom.FONTE_POWER
            if not bairro and lido.bairro:
                bairro, fonte = lido.bairro, dom.FONTE_POWER

        # 4. Planilha da PowerCentral
        importado_power = importados["conta"].get(chave_conta)
        if not cidade and importado_power is not None:
            cidade = importado_power.cidade
            bairro = bairro or importado_power.bairro
            fonte = fonte or dom.FONTE_POWER_PLANILHA
        if coordenada is None and importado_power is not None:
            coordenada = geo.coordenada_valida(importado_power.lat, importado_power.lon)

        # 5. Correção à mão — vence tudo. Alguém olhou e decidiu; uma
        # leitura automática não tem autoridade para desfazer isso, nem
        # quando o catálogo é gerado de novo.
        manual = manuais.get(chave_conta)
        if manual is not None and manual.bairro:
            bairro = manual.bairro
            cidade = manual.cidade or cidade
            fonte = dom.FONTE_MANUAL

        lat, lon = coordenada if coordenada else (None, None)
        clientes.append(
            dom.ClienteBase(
                conta=conta, nome=nome, bairro=bairro, cidade=cidade, fonte=fonte,
                lat=lat, lon=lon,
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
    }

    ciclo = _gravar_ciclo(clientes, resumo=resumo, user=user)
    audit_service.registrar(
        action="rotas_catalogo_gerado",
        result="success",
        user=user,
        details={
            "ciclo": ciclo.numero,
            "base": resumo["base"],
            "com_bairro": resumo["com_bairro"],
            "regioes": resumo["regioes"],
        },
    )
    return ciclo


# ----------------------------------------------------------------------
# O ciclo de preventivas (persistido — ver `models/rotas.RotasCiclo`)
# ----------------------------------------------------------------------


def ciclo_atual() -> RotasCiclo | None:
    """A rodada em aberto, ou nada se nunca se gerou catálogo."""
    return (
        RotasCiclo.query.filter(RotasCiclo.encerrado_em.is_(None))
        .order_by(RotasCiclo.numero.desc())
        .first()
    )


def _gravar_ciclo(clientes, *, resumo: dict, user=None) -> RotasCiclo:
    """Grava o catálogo na rodada em aberto, **preservando as visitas**.

    Gerar de novo no meio de uma rodada é normal (importou planilha nova,
    entrou conta nova), e perder o que já foi visitado faria o técnico
    repetir locais — exatamente o que a marcação existe para evitar. Por
    isso a lista é substituída, mas a marca de cada conta que continua no
    catálogo é recolocada."""
    ciclo = ciclo_atual()
    if ciclo is None:
        ultimo = RotasCiclo.query.order_by(RotasCiclo.numero.desc()).first()
        ciclo = RotasCiclo(numero=(ultimo.numero + 1) if ultimo else 1)
        db.session.add(ciclo)
        db.session.flush()

    visitas = {
        linha.conta: (linha.visitado_em, linha.visitado_por_user_id)
        for linha in ciclo.clientes
        if linha.visitado_em is not None
    }
    # Apagado uma a uma, pela ORM, e não com um DELETE em massa: o
    # `delete(synchronize_session=False)` deixa as linhas apagadas no
    # mapa de identidade da sessão, e como o SQLite reaproveita id, as
    # novas colidiam com elas ("identity map already had an identity").
    # Deu certo por sorte aqui; é o tipo de coisa que vira bug de dado
    # trocado quando a lista cresce.
    for linha in ciclo.clientes.all():
        db.session.delete(linha)
    db.session.flush()

    for cliente in clientes:
        visitado_em, visitado_por = visitas.get(cliente.conta, (None, None))
        db.session.add(
            RotasCicloCliente(
                ciclo_id=ciclo.id,
                conta=cliente.conta,
                nome=cliente.nome[:200],
                bairro=cliente.bairro[:120],
                cidade=cliente.cidade[:120],
                fonte=cliente.fonte[:32],
                lat=cliente.lat,
                lon=cliente.lon,
                visitado_em=visitado_em,
                visitado_por_user_id=visitado_por,
            )
        )

    ciclo.resumo = resumo
    ciclo.atualizado_em = datetime.now(timezone.utc)
    ciclo.criado_por_user_id = getattr(user, "id", ciclo.criado_por_user_id)
    db.session.flush()
    return ciclo


def catalogo(ciclo: RotasCiclo | None) -> dict:
    """O que a tela mostra: regiões montadas a partir do ciclo gravado.

    O agrupamento é refeito aqui, e não guardado: ele é função pura do que
    está nas linhas, e guardar duas representações da mesma coisa é como
    elas começam a divergir."""
    if ciclo is None:
        return {"regioes": [], "resumo": {}, "visitados": 0, "total": 0}

    linhas = ciclo.clientes.all()
    visitado_por_conta = {linha.conta: linha for linha in linhas}
    regioes = dom.agrupar_por_regiao(
        [
            dom.ClienteBase(
                conta=linha.conta,
                nome=linha.nome,
                bairro=linha.bairro,
                cidade=linha.cidade,
                fonte=linha.fonte,
                lat=linha.lat,
                lon=linha.lon,
            )
            for linha in linhas
        ]
    )
    return {
        "regioes": regioes,
        "resumo": ciclo.resumo or {},
        "linhas": visitado_por_conta,
        "visitados": sum(1 for linha in linhas if linha.visitado_em is not None),
        "total": len(linhas),
        "com_coordenada": sum(1 for linha in linhas if linha.lat is not None),
    }


def marcar_visita(ciclo: RotasCiclo, conta: str, *, visitado: bool, user=None) -> bool:
    """Marca (ou desmarca) a visita de uma conta. Devolve o estado final.

    Desmarcar existe porque marcar errado é fácil e inevitável — sem o
    desfazer, o único conserto seria reiniciar a rodada inteira e perder
    todas as outras marcas."""
    linha = ciclo.clientes.filter(RotasCicloCliente.conta == conta).first()
    if linha is None:
        raise RotasError(f"A conta {conta} não está neste ciclo.")

    linha.visitado_em = datetime.now(timezone.utc) if visitado else None
    linha.visitado_por_user_id = getattr(user, "id", None) if visitado else None
    ciclo.atualizado_em = datetime.now(timezone.utc)
    db.session.flush()

    audit_service.registrar(
        action="rotas_visita_marcada" if visitado else "rotas_visita_desmarcada",
        result="success",
        user=user,
        details={"ciclo": ciclo.numero, "conta": conta},
    )
    return visitado


def reiniciar_ciclo(ciclo: RotasCiclo, *, user=None) -> RotasCiclo:
    """Fecha a rodada e abre a próxima com os mesmos clientes, sem marcas.

    Não consulta plataforma nenhuma: a lista de clientes é a mesma que
    acabou de ser percorrida, e refazer a varredura só para zerar as
    marcas custaria minutos para não mudar nada. Quem quiser a lista
    atualizada clica em "gerar catálogo" depois."""
    agora = datetime.now(timezone.utc)
    linhas = ciclo.clientes.all()

    ciclo.encerrado_em = agora
    novo = RotasCiclo(
        numero=ciclo.numero + 1,
        iniciado_em=agora,
        atualizado_em=agora,
        criado_por_user_id=getattr(user, "id", None),
        resumo=ciclo.resumo or {},
    )
    db.session.add(novo)
    db.session.flush()

    for linha in linhas:
        db.session.add(
            RotasCicloCliente(
                ciclo_id=novo.id,
                conta=linha.conta,
                nome=linha.nome,
                bairro=linha.bairro,
                cidade=linha.cidade,
                fonte=linha.fonte,
                lat=linha.lat,
                lon=linha.lon,
            )
        )
    db.session.flush()

    audit_service.registrar(
        action="rotas_ciclo_reiniciado",
        result="success",
        user=user,
        details={"encerrado": ciclo.numero, "novo": novo.numero, "clientes": len(linhas)},
    )
    return novo


def definir_bairro_manual(
    ciclo: RotasCiclo | None, conta: str, *, bairro: str, cidade: str = "", user=None
) -> dict:
    """Corrige o bairro de uma conta à mão, para sempre.

    A correção é gravada fora do ciclo (`RotasBairroManual`) de propósito:
    ela precisa sobreviver a gerar o catálogo de novo e a reiniciar a
    rodada. Se morasse no ciclo, a próxima geração desfaria o trabalho de
    quem corrigiu, em silêncio.

    Bairro vazio **apaga** a correção — é como se volta a confiar na
    leitura automática depois de arrumar o cadastro na origem."""
    conta_chave = str(conta or "").strip().lstrip("0")
    bairro = " ".join(str(bairro or "").split())[:120]
    cidade = " ".join(str(cidade or "").split())[:120]

    linha_ciclo = None
    if ciclo is not None:
        linha_ciclo = ciclo.clientes.filter(RotasCicloCliente.conta == conta).first()
        if linha_ciclo is None:
            raise RotasError(f"A conta {conta} não está neste ciclo.")

    manual = RotasBairroManual.query.filter_by(conta=conta_chave).first()
    if not bairro:
        if manual is not None:
            db.session.delete(manual)
        acao, aplicado = "rotas_bairro_manual_removido", ""
    else:
        if manual is None:
            manual = RotasBairroManual(conta=conta_chave)
            db.session.add(manual)
        manual.bairro = bairro
        manual.cidade = cidade
        manual.atualizado_em = datetime.now(timezone.utc)
        manual.atualizado_por_user_id = getattr(user, "id", None)
        acao, aplicado = "rotas_bairro_manual", bairro

    # O ciclo em aberto passa a mostrar a correção na hora. Sem isto, a
    # pessoa corrigiria o bairro e a tela continuaria igual até a próxima
    # geração — que leva minutos e ninguém vai rodar por uma linha.
    if linha_ciclo is not None:
        linha_ciclo.bairro = aplicado
        linha_ciclo.cidade = cidade or linha_ciclo.cidade
        linha_ciclo.fonte = dom.FONTE_MANUAL if aplicado else ""
        ciclo.atualizado_em = datetime.now(timezone.utc)

    db.session.flush()
    audit_service.registrar(
        action=acao,
        result="success",
        user=user,
        details={"conta": conta, "bairro": aplicado, "cidade": cidade},
    )
    return {"conta": conta, "bairro": aplicado, "cidade": cidade}


def bairros_conhecidos() -> list[str]:
    """Bairros já usados, para a tela sugerir em vez de pedir digitação.

    Digitar "Padre Eustaquio" onde o resto da base tem "Padre Eustáquio"
    criaria duas regiões para o mesmo lugar — e a lista de sugestões é a
    forma barata de isso não acontecer."""
    vistos = {
        linha.bairro
        for linha in RotasEndereco.query.filter(RotasEndereco.bairro != "").all()
    }
    vistos.update(
        linha.bairro for linha in RotasBairroManual.query.all() if linha.bairro
    )
    # O ciclo também entra: quando o bairro vem da API da Auvo ele nunca
    # passa pela tabela de planilhas, e quem só usa a API ficaria sem
    # sugestão nenhuma — justamente a situação em que a divergência de
    # grafia nasce.
    ciclo = ciclo_atual()
    if ciclo is not None:
        vistos.update(
            linha.bairro for linha in ciclo.clientes.all() if linha.bairro
        )
    return sorted(vistos, key=dom_end.normalizar)
