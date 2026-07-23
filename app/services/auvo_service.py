"""Orquestração da abertura de chamados na Auvo (§4-§5 do complemento).

Fluxo de cada chamado: de-para → cooldown → simulação/produção → registro
em `auvo_chamados` + auditoria. Regras herdadas do motor validado:

- só linha do de-para com status OK e id_auvo preenchido abre;
- cooldown (padrão 12h) conta APENAS a partir de criação real ('aberta') —
  simulação nunca grava estado de dedup, senão bloquearia a execução real;
- em simulação nada é enviado à Auvo: registra-se o que SERIA enviado;
- falha guarda corpo enviado + resposta para diagnóstico e nunca derruba
  o coletor nem a geração de relatório (os gatilhos embrulham tudo).

Para o histórico não virar ruído com o ciclo de 5 min (uma conta parada
geraria uma linha a cada ciclo), resultados repetidos de uma mesma conta
('simulada'/'repetida'/'sem_depara'/'falha') não são regravados dentro da
janela de cooldown — a linha existente já conta a história.
"""

from __future__ import annotations

import csv
import io
import logging
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from app.extensions import db
from app.integrations.auvo_client import AuvoClient, AuvoCredentials, AuvoError
from app.models.auvo import AuvoChamado, AuvoDepara
from app.services import audit_service, settings_service

logger = logging.getLogger("auvo")

SCORE_CASAMENTO_SEGURO = 0.90  # >= vira OK na regeração; abaixo, REVISAR

GATILHO_SEM_COMUNICACAO = "sem_comunicacao"
GATILHO_DISPAROS = "disparos"

_TEMPLATE_POR_GATILHO = {GATILHO_SEM_COMUNICACAO: "semcom", GATILHO_DISPAROS: "disparos"}


def normalizar_conta(conta: object) -> str:
    """'0095' e '95' são a mesma conta (regra do motor validado)."""
    return str(conta or "").strip().lstrip("0") or "0"


def criar_cliente(config) -> AuvoClient | None:
    credenciais = settings_service.get_auvo_credentials(
        encryption_key=config["ENCRYPTION_KEY"]
    )
    if credenciais is None:
        return None
    return AuvoClient(AuvoCredentials(api_key=credenciais[0], api_token=credenciais[1]))


class _Contexto(dict):
    """Placeholders desconhecidos ficam literais em vez de KeyError —
    template é editável pelo admin e não pode derrubar o gatilho."""

    def __missing__(self, chave: str) -> str:  # pragma: no cover - trivial
        return "{" + chave + "}"


def renderizar_template(gatilho: str, parte: str, contexto: dict) -> str:
    template = settings_service.get_auvo_template(_TEMPLATE_POR_GATILHO[gatilho], parte)
    return template.format_map(_Contexto(contexto))


def montar_payload(id_auvo: int, titulo: str, descricao: str) -> dict:
    """O payload validado (§2): título na 1ª linha da orientation, sem
    keyWords, prioridade numérica; idUserTo só quando atribuição ligada."""
    corpo: dict = {
        "customerId": int(id_auvo),
        "orientation": f"{titulo}\n{descricao}" if titulo else descricao,
        "priority": settings_service.get_auvo_priority(),
    }
    task_type = settings_service.get_auvo_task_type()
    if task_type is not None:
        corpo["taskType"] = task_type
    criador = settings_service.get_auvo_criador_id()
    if criador is not None:
        corpo["idUserFrom"] = criador
    responsavel = settings_service.get_auvo_responsavel_id()
    if settings_service.auvo_atribuir_responsavel() and responsavel is not None:
        corpo["idUserTo"] = responsavel
    return corpo


def _agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def _ja_registrado_na_janela(conta: str, gatilho: str, resultado: str, horas: float) -> bool:
    limite = _agora_utc() - timedelta(hours=horas)
    return (
        AuvoChamado.query.filter_by(
            conta_power=conta, gatilho=gatilho, resultado=resultado
        )
        .filter(AuvoChamado.criado_em >= limite)
        .first()
        is not None
    )


def _em_cooldown(conta: str, horas: float) -> bool:
    """Só criação REAL ('aberta') conta para o dedup — por especificação,
    simulação não persiste estado."""
    limite = _agora_utc() - timedelta(hours=horas)
    return (
        AuvoChamado.query.filter_by(conta_power=conta, resultado="aberta")
        .filter(AuvoChamado.criado_em >= limite)
        .first()
        is not None
    )


def _registrar(
    *,
    gatilho: str,
    conta: str,
    cliente: str,
    resultado: str,
    origem_user_id: int | None = None,
    id_tarefa_auvo: str | None = None,
    request_body: dict | None = None,
    response_body: object = None,
    erro: str | None = None,
) -> AuvoChamado:
    if response_body is not None and not isinstance(response_body, (dict, list)):
        response_body = {"texto": str(response_body)[:2000]}
    chamado = AuvoChamado(
        gatilho=gatilho,
        conta_power=conta,
        cliente=cliente,
        resultado=resultado,
        origem_user_id=origem_user_id,
        id_tarefa_auvo=id_tarefa_auvo,
        request_body=request_body,
        response_body=response_body,
        erro=erro,
    )
    db.session.add(chamado)
    audit_service.registrar(
        action="auvo_chamado",
        result="failure" if resultado == "falha" else "success",
        details={
            "gatilho": gatilho,
            "conta": conta,
            "cliente": cliente,
            "resultado": resultado,
            "id_tarefa_auvo": id_tarefa_auvo,
            "erro": erro,
        },
    )
    db.session.flush()
    return chamado


def _extrair_task_id(resposta: object) -> str | None:
    if isinstance(resposta, dict):
        res = resposta.get("result", resposta)
        if isinstance(res, dict):
            for chave in ("taskID", "taskId", "id"):
                valor = res.get(chave)
                if valor:
                    return str(valor)
    return None


def abrir_chamado(
    *,
    gatilho: str,
    conta: object,
    nome: str,
    contexto: dict,
    config,
    origem_user_id: int | None = None,
    client: AuvoClient | None = None,
) -> AuvoChamado | None:
    """Abre (ou simula) um chamado para uma conta da PowerCentral.
    Devolve o registro criado, ou None quando o resultado repetiria uma
    linha recente do histórico (anti-ruído do ciclo de 5 min)."""
    conta_norm = normalizar_conta(conta)
    cooldown = settings_service.get_auvo_cooldown_horas()

    def _skip_ou_registra(resultado: str, **kwargs) -> AuvoChamado | None:
        if _ja_registrado_na_janela(conta_norm, gatilho, resultado, cooldown):
            return None
        return _registrar(
            gatilho=gatilho,
            conta=conta_norm,
            cliente=nome,
            resultado=resultado,
            origem_user_id=origem_user_id,
            **kwargs,
        )

    linha = AuvoDepara.query.filter_by(conta_power=conta_norm).first()
    if linha is None or not linha.abre_chamado:
        return _skip_ou_registra("sem_depara")

    if _em_cooldown(conta_norm, cooldown):
        return _skip_ou_registra("repetida")

    contexto_completo = dict(contexto)
    contexto_completo.setdefault("conta", conta_norm)
    contexto_completo.setdefault("nome", nome)
    titulo = renderizar_template(gatilho, "titulo", contexto_completo)
    descricao = renderizar_template(gatilho, "descricao", contexto_completo)
    payload = montar_payload(linha.id_auvo, titulo, descricao)

    if settings_service.auvo_simulacao():
        logger.info(
            "Auvo SIMULAÇÃO — abriria tarefa para %s (%s): %s", conta_norm, nome, titulo
        )
        return _skip_ou_registra("simulada", request_body=payload)

    if "idUserFrom" not in payload:
        return _skip_ou_registra(
            "falha",
            request_body=payload,
            erro="criador_id (idUserFrom) não configurado — obrigatório para abrir tarefa.",
        )

    auvo = client or criar_cliente(config)
    if auvo is None:
        return _skip_ou_registra(
            "falha",
            request_body=payload,
            erro="Credenciais da Auvo não configuradas.",
        )

    try:
        resposta = auvo.criar_tarefa(payload)
    except AuvoError as exc:
        logger.warning("Auvo — falha ao criar tarefa para %s: %s", conta_norm, exc)
        return _skip_ou_registra(
            "falha",
            request_body=exc.corpo_enviado or payload,
            response_body=exc.resposta,
            erro=str(exc),
        )

    logger.info("Auvo — tarefa criada para %s (%s).", conta_norm, nome)
    return _registrar(
        gatilho=gatilho,
        conta=conta_norm,
        cliente=nome,
        resultado="aberta",
        origem_user_id=origem_user_id,
        id_tarefa_auvo=_extrair_task_id(resposta),
        request_body=payload,
        response_body=resposta if isinstance(resposta, (dict, list)) else None,
    )


# ----------------------------------------------------------------------
# Gatilhos (§4) — chamados pelo coletor e pela geração de Disparos
# ----------------------------------------------------------------------


def _formatar_sinal(codigo: str | None, quando: datetime | None) -> str:
    if not codigo:
        return "desconhecido"
    if quando is None:
        return codigo
    return f"{codigo} em {quando:%d/%m/%Y %H:%M}"


def processar_sem_comunicacao(
    contas,
    *,
    config,
    agora: datetime,
    client: AuvoClient | None = None,
) -> list[AuvoChamado]:
    """Gatilho do coletor: abre chamado para contas sem comunicação real
    há pelo menos `sem_comunicacao_horas_minimas` (evita chamado por
    queda passageira)."""
    minimo = timedelta(hours=settings_service.get_auvo_sem_comunicacao_horas_minimas())
    abertos: list[AuvoChamado] = []
    for conta in contas:
        desde = conta.tst_failure_since
        if desde is None or (agora - desde) < minimo:
            continue
        chamado = abrir_chamado(
            gatilho=GATILHO_SEM_COMUNICACAO,
            conta=conta.account_number,
            nome=conta.account_name or "",
            contexto={
                "desde": f"{desde:%d/%m/%Y %H:%M}",
                "sinal": _formatar_sinal(conta.last_event_code, conta.last_event_at),
            },
            config=config,
            client=client,
        )
        if chamado is not None:
            abertos.append(chamado)
    return abertos


def processar_disparos(
    clientes,
    *,
    config,
    origem_user_id: int | None = None,
    client: AuvoClient | None = None,
) -> list[AuvoChamado]:
    """Gatilho da geração de Disparos: abre chamado para clientes com
    pelo menos `disparos_minimos_tarefa` disparos válidos no período."""
    minimo = settings_service.get_auvo_disparos_minimos_tarefa()
    abertos: list[AuvoChamado] = []
    for cliente in clientes:
        if cliente.quantidade < minimo:
            continue
        chamado = abrir_chamado(
            gatilho=GATILHO_DISPAROS,
            conta=cliente.conta_numero or cliente.conta_id,
            nome=cliente.cliente,
            contexto={
                "qtd": str(cliente.quantidade),
                "zonas": ", ".join(cliente.zonas) or "não informadas",
            },
            config=config,
            origem_user_id=origem_user_id,
            client=client,
        )
        if chamado is not None:
            abertos.append(chamado)
    return abertos


# ----------------------------------------------------------------------
# De-para (§3): importação do CSV do protótipo e regeração por nome
# ----------------------------------------------------------------------


def _normalizar_status(bruto: str) -> str:
    texto = _sem_acentos(str(bruto or "").strip()).upper()
    if texto == "OK":
        return "OK"
    if texto == "REVISAR":
        return "REVISAR"
    return "NAO"  # "Não", "NAO", vazio etc. = não abre chamado


def _sem_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


def importar_depara_csv(conteudo: str, *, updated_by_id: int | None = None) -> dict:
    """Importa o `depara_power_auvo.csv` do protótipo
    (`conta_power;nome_power;id_auvo;nome_auvo;score;status`), fazendo
    upsert por conta. Devolve contadores para feedback na tela."""
    leitor = csv.DictReader(io.StringIO(conteudo), delimiter=";")
    criadas = atualizadas = ignoradas = 0
    for linha_csv in leitor:
        conta = normalizar_conta(linha_csv.get("conta_power"))
        if not conta or conta == "0":
            ignoradas += 1
            continue
        try:
            id_auvo = int(str(linha_csv.get("id_auvo", "")).strip() or 0) or None
        except ValueError:
            id_auvo = None
        try:
            score = float(str(linha_csv.get("score", "")).strip().replace(",", "."))
        except ValueError:
            score = None

        linha = AuvoDepara.query.filter_by(conta_power=conta).first()
        if linha is None:
            linha = AuvoDepara(conta_power=conta)
            db.session.add(linha)
            criadas += 1
        else:
            atualizadas += 1
        linha.nome_power = str(linha_csv.get("nome_power", "")).strip()
        linha.id_auvo = id_auvo
        linha.nome_auvo = str(linha_csv.get("nome_auvo", "")).strip() or None
        linha.score = score
        linha.status = _normalizar_status(linha_csv.get("status", ""))
        linha.updated_by_user_id = updated_by_id
    db.session.flush()
    return {"criadas": criadas, "atualizadas": atualizadas, "ignoradas": ignoradas}


def _nome_para_casamento(nome: str) -> str:
    return " ".join(_sem_acentos(nome or "").upper().split())


def _nome_cliente_auvo(cliente: dict) -> str:
    for chave in ("description", "name", "nome", "razaoSocial", "corporateName"):
        valor = str(cliente.get(chave) or "").strip()
        if valor:
            return valor
    return ""


def _id_cliente_auvo(cliente: dict) -> int | None:
    for chave in ("id", "customerId", "idCustomer"):
        valor = cliente.get(chave)
        if valor is not None:
            try:
                return int(valor)
            except (TypeError, ValueError):
                continue
    return None


def regerar_depara(*, client: AuvoClient, updated_by_id: int | None = None) -> dict:
    """Recasa por similaridade de nome as linhas ainda não revisadas
    (status REVISAR), contra os clientes atuais da Auvo. Linhas OK/NAO
    (revisadas por humano) são preservadas intactas."""
    clientes_auvo = [
        (cid, nome, _nome_para_casamento(nome))
        for cliente in client.listar_clientes()
        if (cid := _id_cliente_auvo(cliente)) is not None
        and (nome := _nome_cliente_auvo(cliente))
    ]

    recasadas = preservadas = 0
    for linha in AuvoDepara.query.all():
        if linha.status in ("OK", "NAO"):
            preservadas += 1
            continue
        alvo = _nome_para_casamento(linha.nome_power)
        melhor_score, melhor = 0.0, None
        for cid, nome, nome_norm in clientes_auvo:
            score = SequenceMatcher(None, alvo, nome_norm).ratio()
            if score > melhor_score:
                melhor_score, melhor = score, (cid, nome)
        if melhor is not None:
            linha.id_auvo, linha.nome_auvo = melhor
            linha.score = round(melhor_score, 2)
            linha.status = "OK" if melhor_score >= SCORE_CASAMENTO_SEGURO else "REVISAR"
            linha.updated_by_user_id = updated_by_id
            recasadas += 1
    db.session.flush()
    return {"recasadas": recasadas, "preservadas": preservadas}
