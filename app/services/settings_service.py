from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.extensions import db
from app.models.settings import Setting

# Valores padrão (regra 6.1/6.2 — seção 6 do prompt). RF7 permite ajustar
# pela interface; enquanto não houver linha em `settings`, vale o padrão.
DEFAULTS: dict[str, str] = {
    "window_hours": "3",
    "confirming_codes": "TST,CLO,OPN",
    "collector_interval_minutes": "5",
    "watchdog_threshold_minutes": "15",
    "manual_cooldown_seconds": "60",
    "retention_days": "90",
    "show_false_positives_in_panel": "true",
    "periodic_report_enabled": "false",
    "periodic_report_interval_minutes": "60",
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    # Módulo Atendimentos (A.5)
    "atend_codigos_evento": "NYE,NYC",
    "atend_incluir_automaticos": "false",
    "atend_incluir_abertos": "false",
    "atend_resolucao_indica_arme": "ativado,armado remotamente,armamento confirmado",
    "atend_horas_primeira_execucao": "24",
    "atend_horas_arme_posterior": "12",
    # Módulo Disparos (B.5)
    "disp_horas_primeira_execucao": "24",
    "disp_limite_recorrente": "15",
    "disp_ignorar_zonas": "PANICO",
    # Módulo Disparos Geral (fim de semana)
    "dispg_limite_recorrente": "50",
    "dispg_grupo_villefort": "VILLEFORT",
    "dispg_grupo_super_nosso": "SUPER NOSSO,APOIO",
    # Módulo Chamados Auvo (§4/§5 do complemento) — simulação LIGADA por
    # padrão: só desligar depois de validar de-para e payload.
    "auvo_api_key": "",
    "auvo_api_token": "",
    "auvo_simulacao": "true",
    "auvo_criador_id": "",
    "auvo_responsavel_id": "",
    "auvo_atribuir_responsavel": "true",
    "auvo_task_type": "",
    # Vazio = usa `auvo_task_type`. Preenchido, o chamado de sem-comunicação
    # abre com tipo próprio ("falha de comunicação"), separado do de alarme.
    "auvo_task_type_sem_comunicacao": "",
    "auvo_priority": "2",
    "auvo_cooldown_horas": "12",
    "auvo_sem_comunicacao_horas_minimas": "3",
    "auvo_disparos_minimos_tarefa": "5",
    # Disparos Geral conta TODOS os disparos (número bem maior) — limite próprio
    "auvo_disp_geral_minimos_tarefa": "30",
    "auvo_template_semcom_titulo": "Cliente sem comunicacao - {conta} {nome}",
    "auvo_template_semcom_descricao": (
        "Cliente sem comunicacao desde {desde}. "
        "Ultimo evento recebido: {sinal}. Verificar em campo."
    ),
    "auvo_template_disparos_titulo": "Disparos aleatorios - {conta} {nome}",
    "auvo_template_disparos_descricao": (
        "{qtd} disparo(s) aleatorio(s) no periodo. "
        "Zonas: {zonas}. Avaliar sensores/instalacao."
    ),
    # Módulo Relatório do Técnico do Dia
    "tecnico_nome_padrao": "",
    "tecnico_codigos_padrao": "CLO,OPN,BUR,BYP,ROP,RCL",
    "tecnico_periodo_dias_padrao": "30",
    "tecnico_saida_xlsx_convertido": "false",
    # Módulo BI: Eficácia do Técnico
    "bi_janela_dias": "15",
    "bi_limiar_melhora": "20",
    "bi_limiar_piora": "20",
    "bi_tipos_intervencao": "",  # vazio = todos os tipos de tarefa contam
    "bi_visitas_para_cronico": "3",
    "bi_periodo_padrao_dias": "90",
    "bi_amostra_minima_tecnico": "5",
    # --- Bot do técnico no Telegram ---
    "bot_ativado": "false",
    "bot_tecnicos_ids": "",  # ids de usuário do Telegram, separados por vírgula
    "bot_relatorio_dias_padrao": "7",
    "bot_relatorio_codigos": "CLO,OPN,BUR,BYP,ROP,RCL",
    "bot_cooldown_segundos": "10",
    # Confirmação do long polling: último update já processado. Evita
    # reprocessar comando antigo quando o serviço reinicia.
    "bot_update_offset": "",
    # --- Diagnóstico automático da conta (bot) ---
    # Limiares do que vira achado. Editáveis porque "muito disparo" numa
    # loja de rua não é o mesmo que num condomínio.
    # Disparo espalhado pela conta (vários pontos) — pergunta "esta conta
    # dispara muito?".
    "diag_disparos_limiar": "5",
    # Disparo repetido NA MESMA zona — pergunta diferente: "este ponto
    # está com defeito?". Três na mesma zona já é padrão, não azar.
    "diag_disparos_zona_limiar": "3",
    "diag_bypass_limiar": "3",
    # Comunicação: o total no período levanta a suspeita...
    "diag_comunicacao_limiar": "4",
    # ...e a MÉDIA POR DIA diz a gravidade. 300 falhas em 15 dias é um
    # painel caindo o tempo todo; 5 em 15 dias é ruído. Sem a taxa, os
    # dois viravam o mesmo aviso.
    "diag_comunicacao_por_dia_alta": "1",
    # Códigos do catálogo `codigosalarmas` da plataforma (HAR 07/10), já
    # filtrados para painel de alarme. Ficam em configuração porque o
    # código exato depende do MODELO do painel de cada cliente: faltando
    # algum, acrescente aqui sem mexer no sistema.
    # NYR painel de alarme off-line (falha no teste periódico) — é ESTE
    # que a plataforma usa de verdade, confirmado numa conta que oscilava
    # e saía como "sem problemas"; o `FST` do catálogo genérico não
    # aparece na base. TST (teste OK) é a restauração e NÃO entra aqui.
    # EPC perda de comunicações · FCS sensores · FCR rádio não responde ·
    # FCW Wi-Fi · PSC/PSP/PSG/PSS supervisão (sensor/pânico/PGM/sirene).
    "diag_codigos_comunicacao": "NYR,EPC,FST,FCS,FCR,FCW,PSC,PSP,PSG,PSS",
    # _BT/E41 bateria morta · BTF falha no teste · BTM ausente · N36 falta
    # · BBF/BFS/PTS/PBC fraca (sem fio/sensor/teclado/controle) · P51 low
    # battery report.
    "diag_codigos_painel_bateria": "_BT,E41,BTF,BTM,N36,BBF,BFS,PTS,PBC,P51",
    # E40/POW falha de energia · N34 falta · PET teclado sem fio ·
    # RCV/X13 AC fail (painéis específicos).
    "diag_codigos_painel_ac": "E40,POW,N34,PET,RCV,X13",
    # TAM painel aberto · TPT teclado · UST usuário · PST sensor.
    "diag_codigos_painel_tamper": "TAM,TPT,UST,PST",
    # Descrição do evento -> código, no formato `descrição=CÓDIGO`, um por
    # linha. Existe porque o EXPORT NÃO TRAZ O CÓDIGO: a tela mostra
    # "NYR - Falha no Teste Periódico", o arquivo guarda só a descrição.
    # Sem a tradução, nenhuma regra funciona (disparo, arme e desarme
    # dependem do código tanto quanto comunicação e painel).
    # Vazio = usa o mapa padrão de `domain/catalogo_eventos.py`, que só
    # tem o confirmado em export real. Para o catálogo completo da
    # plataforma, use scripts/importar_catalogo_codigos.py.
    "diag_descricoes": "",
    # --- Auditoria de Horários ---
    # A varredura é uma consulta por conta, em toda a base. 0 = sem pausa;
    # subir só se o portal reclamar do ritmo.
    "horarios_pausa_segundos": "0",
    # Módulo Links da Central do Cliente (Auvo) — simulação LIGADA por
    # padrão: módulo de maior risco do sistema (escreve contatos reais com
    # link de acesso sem login/senha na Auvo). Só desligar depois de
    # confirmar o endpoint interno (docs/CENTRAL_CLIENTE.md §6).
    "central_simulacao": "true",
    "central_score_minimo": "0.70",
    "central_auvo_user_request": "",
    "central_menu_solicitacoes": "true",
    "central_menu_os": "true",
    "central_menu_orcamento": "false",
    "central_pausa_segundos": "1",
    "central_cargo_padrao": "Cliente",
    "central_gerar_login_senha": "false",
    "central_whatsapp_ddi": "55",
    "central_whatsapp_template": (
        "Olá, {nome}! Aqui é da Novo Millenium.\n\n"
        "Este é o seu acesso à Central do Cliente, onde você acompanha e abre "
        "seus atendimentos de forma rápida e sem burocracia:\n"
        "{link}\n\n"
        "Como usar:\n"
        "1) Toque no link (não pede login nem senha);\n"
        "2) Para pedir um atendimento, use \"Solicitações\";\n"
        "3) Para acompanhar um serviço, veja em \"Ordens de Serviço\".\n\n"
        "Guarde este link com você — ele é o seu acesso pessoal à nossa central.\n\n"
        "Ficou com alguma dúvida ou dificuldade para abrir suas ordens? É só "
        "me acionar aqui mesmo por este WhatsApp que o suporte resolve com você!"
    ),
}

_TELEGRAM_TOKEN_KEY = "telegram_bot_token"
_TELEGRAM_CHAT_KEY = "telegram_chat_id"
_AUVO_KEY_KEY = "auvo_api_key"
_AUVO_TOKEN_KEY = "auvo_api_token"


def get(key: str) -> str:
    setting = db.session.get(Setting, key)
    if setting is not None and setting.value is not None:
        return setting.value
    return DEFAULTS.get(key, "")


def set(key: str, value: str, *, updated_by_id: int | None = None) -> Setting:
    setting = db.session.get(Setting, key)
    if setting is None:
        setting = Setting(key=key)
        db.session.add(setting)
    setting.value = value
    setting.updated_by_id = updated_by_id
    return setting


def get_window_hours() -> float:
    return float(get("window_hours"))


def get_confirming_codes() -> tuple[str, ...]:
    bruto = get("confirming_codes")
    return tuple(codigo.strip() for codigo in bruto.split(",") if codigo.strip())


def get_collector_interval_minutes() -> int:
    return int(get("collector_interval_minutes"))


def get_watchdog_threshold_minutes() -> float:
    return float(get("watchdog_threshold_minutes"))


def get_manual_cooldown_seconds() -> int:
    return int(get("manual_cooldown_seconds"))


def get_retention_days() -> int:
    return int(get("retention_days"))


def show_false_positives_in_panel() -> bool:
    return get("show_false_positives_in_panel").strip().lower() == "true"


def periodic_report_enabled() -> bool:
    return get("periodic_report_enabled").strip().lower() == "true"


def get_periodic_report_interval_minutes() -> int:
    return int(get("periodic_report_interval_minutes"))


def _lista(chave: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in get(chave).split(",") if item.strip())


# --- Módulo Atendimentos (A.5) ---


def get_atend_codigos_evento() -> tuple[str, ...]:
    return _lista("atend_codigos_evento")


def atend_incluir_automaticos() -> bool:
    return get("atend_incluir_automaticos").strip().lower() == "true"


def atend_incluir_abertos() -> bool:
    return get("atend_incluir_abertos").strip().lower() == "true"


def get_atend_resolucao_indica_arme() -> tuple[str, ...]:
    return _lista("atend_resolucao_indica_arme")


def get_atend_horas_primeira_execucao() -> int:
    return int(get("atend_horas_primeira_execucao"))


def get_atend_horas_arme_posterior() -> int:
    return int(get("atend_horas_arme_posterior"))


# --- Módulo Disparos (B.5) ---


def get_disp_horas_primeira_execucao() -> int:
    return int(get("disp_horas_primeira_execucao"))


def get_disp_limite_recorrente() -> int:
    return int(get("disp_limite_recorrente"))


def get_disp_ignorar_zonas() -> tuple[str, ...]:
    return _lista("disp_ignorar_zonas")


# --- Módulo Disparos Geral (fim de semana) ---


def get_dispg_limite_recorrente() -> int:
    return int(get("dispg_limite_recorrente"))


def get_dispg_grupo_villefort() -> tuple[str, ...]:
    return _lista("dispg_grupo_villefort")


def get_dispg_grupo_super_nosso() -> tuple[str, ...]:
    return _lista("dispg_grupo_super_nosso")


# --- Módulo Chamados Auvo ---


def auvo_simulacao() -> bool:
    return get("auvo_simulacao").strip().lower() == "true"


def _int_ou_none(chave: str) -> int | None:
    bruto = get(chave).strip()
    return int(bruto) if bruto else None


def get_auvo_criador_id() -> int | None:
    return _int_ou_none("auvo_criador_id")


def get_auvo_responsavel_id() -> int | None:
    return _int_ou_none("auvo_responsavel_id")


def auvo_atribuir_responsavel() -> bool:
    return get("auvo_atribuir_responsavel").strip().lower() == "true"


def get_auvo_task_type() -> int | None:
    return _int_ou_none("auvo_task_type")


def get_auvo_task_type_sem_comunicacao() -> int | None:
    return _int_ou_none("auvo_task_type_sem_comunicacao")


def get_auvo_priority() -> int:
    return int(get("auvo_priority"))


def get_auvo_cooldown_horas() -> float:
    return float(get("auvo_cooldown_horas"))


def get_auvo_sem_comunicacao_horas_minimas() -> float:
    return float(get("auvo_sem_comunicacao_horas_minimas"))


def get_auvo_disparos_minimos_tarefa() -> int:
    return int(get("auvo_disparos_minimos_tarefa"))


def get_auvo_disp_geral_minimos_tarefa() -> int:
    return int(get("auvo_disp_geral_minimos_tarefa"))


def get_auvo_template(gatilho: str, parte: str) -> str:
    """gatilho: 'semcom' | 'disparos'; parte: 'titulo' | 'descricao'."""
    return get(f"auvo_template_{gatilho}_{parte}")


def _fernet(encryption_key: str) -> Fernet:
    chave = encryption_key.encode() if isinstance(encryption_key, str) else encryption_key
    return Fernet(chave)


def set_telegram_credentials(
    bot_token: str, chat_id: str, *, encryption_key: str, updated_by_id: int | None = None
) -> None:
    cifra = _fernet(encryption_key)
    set(
        _TELEGRAM_TOKEN_KEY,
        cifra.encrypt(bot_token.encode()).decode(),
        updated_by_id=updated_by_id,
    )
    set(
        _TELEGRAM_CHAT_KEY,
        cifra.encrypt(chat_id.encode()).decode(),
        updated_by_id=updated_by_id,
    )


def get_telegram_credentials(*, encryption_key: str) -> tuple[str, str] | None:
    """Retorna (bot_token, chat_id) decifrados, ou None se ainda não
    configurado ou se a chave de cifra não corresponder ao valor gravado."""
    token_cifrado = get(_TELEGRAM_TOKEN_KEY)
    chat_id_cifrado = get(_TELEGRAM_CHAT_KEY)
    if not token_cifrado or not chat_id_cifrado:
        return None

    cifra = _fernet(encryption_key)
    try:
        token = cifra.decrypt(token_cifrado.encode()).decode()
        chat_id = cifra.decrypt(chat_id_cifrado.encode()).decode()
    except InvalidToken:
        return None
    return token, chat_id


def set_auvo_credentials(
    api_key: str, api_token: str, *, encryption_key: str, updated_by_id: int | None = None
) -> None:
    """Grava apiKey/apiToken da Auvo cifrados (mesmo mecanismo do
    Telegram) — segredos nunca em claro no banco nem no repositório."""
    cifra = _fernet(encryption_key)
    set(_AUVO_KEY_KEY, cifra.encrypt(api_key.encode()).decode(), updated_by_id=updated_by_id)
    set(_AUVO_TOKEN_KEY, cifra.encrypt(api_token.encode()).decode(), updated_by_id=updated_by_id)


def get_auvo_credentials(*, encryption_key: str) -> tuple[str, str] | None:
    """Retorna (api_key, api_token) decifrados, ou None se ainda não
    configurado ou se a chave de cifra não corresponder."""
    key_cifrada = get(_AUVO_KEY_KEY)
    token_cifrado = get(_AUVO_TOKEN_KEY)
    if not key_cifrada or not token_cifrado:
        return None

    cifra = _fernet(encryption_key)
    try:
        api_key = cifra.decrypt(key_cifrada.encode()).decode()
        api_token = cifra.decrypt(token_cifrado.encode()).decode()
    except InvalidToken:
        return None
    return api_key, api_token


# --- Módulo Relatório do Técnico do Dia ---


def get_tecnico_nome_padrao() -> str:
    return get("tecnico_nome_padrao")


def get_tecnico_codigos_padrao() -> tuple[str, ...]:
    return _lista("tecnico_codigos_padrao")


def get_tecnico_periodo_dias_padrao() -> int:
    return int(get("tecnico_periodo_dias_padrao"))


def tecnico_saida_xlsx_convertido() -> bool:
    return get("tecnico_saida_xlsx_convertido").strip().lower() == "true"


# --- Módulo BI: Eficácia do Técnico ---


def get_bi_janela_dias() -> int:
    return int(get("bi_janela_dias"))


def get_bi_limiar_melhora() -> float:
    return float(get("bi_limiar_melhora"))


def get_bi_limiar_piora() -> float:
    return float(get("bi_limiar_piora"))


def get_bi_tipos_intervencao() -> tuple[int, ...]:
    bruto = get("bi_tipos_intervencao")
    valores: list[int] = []
    for item in bruto.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            valores.append(int(item))
        except ValueError:
            continue
    return tuple(valores)


def get_bi_visitas_para_cronico() -> int:
    return int(get("bi_visitas_para_cronico"))


def get_bi_periodo_padrao_dias() -> int:
    return int(get("bi_periodo_padrao_dias"))


def get_bi_amostra_minima_tecnico() -> int:
    return int(get("bi_amostra_minima_tecnico"))


# --- Bot do técnico no Telegram ---


def bot_ativado() -> bool:
    return get("bot_ativado").strip().lower() == "true"


def get_bot_tecnicos_ids() -> tuple[int, ...]:
    """IDs de usuário do Telegram autorizados. Entrada inválida é
    descartada em silêncio: uma vírgula sobrando na configuração não pode
    virar um id que autoriza alguém por engano."""
    ids = []
    for bruto in _lista("bot_tecnicos_ids"):
        try:
            ids.append(int(bruto))
        except ValueError:
            continue
    return tuple(ids)


def get_bot_relatorio_dias_padrao() -> int:
    return int(get("bot_relatorio_dias_padrao"))


def get_bot_relatorio_codigos() -> tuple[str, ...]:
    return _lista("bot_relatorio_codigos")


def get_bot_cooldown_segundos() -> int:
    return int(get("bot_cooldown_segundos"))


def get_bot_update_offset() -> int | None:
    return _int_ou_none("bot_update_offset")


def set_bot_update_offset(offset: int) -> None:
    set("bot_update_offset", str(offset))


# --- Módulo Links da Central do Cliente (Auvo) ---


def central_simulacao() -> bool:
    return get("central_simulacao").strip().lower() == "true"


def get_central_score_minimo() -> float:
    return float(get("central_score_minimo"))


def get_central_auvo_user_request() -> str:
    return get("central_auvo_user_request").strip()


def central_menu_solicitacoes() -> bool:
    return get("central_menu_solicitacoes").strip().lower() == "true"


def central_menu_os() -> bool:
    return get("central_menu_os").strip().lower() == "true"


def central_menu_orcamento() -> bool:
    return get("central_menu_orcamento").strip().lower() == "true"


def get_central_pausa_segundos() -> float:
    return float(get("central_pausa_segundos"))


def get_central_cargo_padrao() -> str:
    return get("central_cargo_padrao")


def central_gerar_login_senha() -> bool:
    return get("central_gerar_login_senha").strip().lower() == "true"


def get_central_whatsapp_ddi() -> str:
    return get("central_whatsapp_ddi").strip() or "55"


def get_central_whatsapp_template() -> str:
    return get("central_whatsapp_template")


# --- Auditoria de Horários ---


def get_horarios_pausa_segundos() -> float:
    return float(get("horarios_pausa_segundos"))


# --- Diagnóstico automático da conta (bot) ---


def get_diag_disparos_limiar() -> int:
    return int(get("diag_disparos_limiar"))


def get_diag_disparos_zona_limiar() -> int:
    return int(get("diag_disparos_zona_limiar"))


def get_diag_comunicacao_por_dia_alta() -> float:
    return float(get("diag_comunicacao_por_dia_alta"))


def get_diag_bypass_limiar() -> int:
    return int(get("diag_bypass_limiar"))


def get_diag_comunicacao_limiar() -> int:
    return int(get("diag_comunicacao_limiar"))


def get_diag_codigos_comunicacao() -> tuple[str, ...]:
    return _lista("diag_codigos_comunicacao")


def get_diag_codigos_painel_bateria() -> tuple[str, ...]:
    return _lista("diag_codigos_painel_bateria")


def get_diag_codigos_painel_ac() -> tuple[str, ...]:
    return _lista("diag_codigos_painel_ac")


def get_diag_codigos_painel_tamper() -> tuple[str, ...]:
    return _lista("diag_codigos_painel_tamper")


def config_diagnostico():
    """Monta a `ConfigDiagnostico` do domínio a partir das configurações —
    o domínio não lê `settings` por conta própria (continua puro)."""
    from app.domain.diagnostico import ConfigDiagnostico

    return ConfigDiagnostico(
        disparos_limiar=get_diag_disparos_limiar(),
        disparos_zona_limiar=get_diag_disparos_zona_limiar(),
        bypass_limiar=get_diag_bypass_limiar(),
        comunicacao_limiar=get_diag_comunicacao_limiar(),
        comunicacao_por_dia_alta=get_diag_comunicacao_por_dia_alta(),
        codigos_comunicacao=get_diag_codigos_comunicacao(),
        codigos_painel_bateria=get_diag_codigos_painel_bateria(),
        codigos_painel_ac=get_diag_codigos_painel_ac(),
        codigos_painel_tamper=get_diag_codigos_painel_tamper(),
        zonas_ignoradas=get_disp_ignorar_zonas(),
    )


def mapa_catalogo_eventos() -> dict[str, str]:
    """Descrição -> código: o mapa padrão com o que estiver configurado por
    cima (configuração vence, para corrigir sem mexer no sistema)."""
    from app.domain import catalogo_eventos as dom_catalogo

    return {**dom_catalogo.MAPA_PADRAO, **dom_catalogo.mapa_de_texto(get("diag_descricoes"))}


def get_diag_codigos_todos() -> tuple[str, ...]:
    """Todos os códigos que o diagnóstico precisa ver no export, sem
    repetir: disparo/arme/desarme/bypass do relatório, mais comunicação e
    painel. É isso que vai no `codigos_alarme` da consulta — assim o
    diagnóstico sai do MESMO arquivo que o técnico recebe, sem uma segunda
    ida ao portal."""
    from app.domain.diagnostico import CODIGO_BYPASS

    codigos = [
        *get_bot_relatorio_codigos(),
        CODIGO_BYPASS,
        *get_diag_codigos_comunicacao(),
        *get_diag_codigos_painel_bateria(),
        *get_diag_codigos_painel_ac(),
        *get_diag_codigos_painel_tamper(),
    ]
    return tuple(dict.fromkeys(c.strip().upper() for c in codigos if c.strip()))
