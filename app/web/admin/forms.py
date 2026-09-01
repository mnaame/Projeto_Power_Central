from flask_wtf import FlaskForm
from wtforms import BooleanField, IntegerField, PasswordField, SelectField, StringField
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class NovoUsuarioForm(FlaskForm):
    username = StringField("Usuário", validators=[DataRequired(), Length(min=3, max=64)])
    password = PasswordField("Senha", validators=[DataRequired(), Length(min=8)])
    role = SelectField(
        "Papel", choices=[("operador", "Operador"), ("admin", "Administrador")]
    )


class TrocarSenhaForm(FlaskForm):
    password = PasswordField("Nova senha", validators=[DataRequired(), Length(min=8)])


class ConfiguracoesForm(FlaskForm):
    window_hours = IntegerField(
        "Janela sem comunicação (horas)", validators=[DataRequired(), NumberRange(min=1, max=72)]
    )
    confirming_codes = StringField(
        "Códigos comprovadores (separados por vírgula)", validators=[DataRequired()]
    )
    collector_interval_minutes = IntegerField(
        "Intervalo do coletor (minutos)", validators=[DataRequired(), NumberRange(min=1, max=180)]
    )
    watchdog_threshold_minutes = IntegerField(
        "Limite do watchdog (minutos)", validators=[DataRequired(), NumberRange(min=1, max=1440)]
    )
    manual_cooldown_seconds = IntegerField(
        "Cooldown do botão manual (segundos)",
        validators=[DataRequired(), NumberRange(min=5, max=3600)],
    )
    retention_days = IntegerField(
        "Retenção de histórico (dias)", validators=[DataRequired(), NumberRange(min=7, max=3650)]
    )
    show_false_positives_in_panel = BooleanField("Mostrar falsos positivos no painel")
    periodic_report_enabled = BooleanField(
        "Enviar relatório periódico no Telegram (mesmo sem mudança na lista)"
    )
    periodic_report_interval_minutes = IntegerField(
        "Intervalo do relatório periódico (minutos)",
        validators=[DataRequired(), NumberRange(min=5, max=1440)],
    )

    # Relatório de Atendimentos (A.5)
    atend_codigos_evento = StringField(
        "Códigos de evento (separados por vírgula)", validators=[DataRequired()]
    )
    atend_incluir_automaticos = BooleanField("Incluir fechamentos automáticos")
    atend_incluir_abertos = BooleanField("Incluir eventos ainda em aberto")
    atend_resolucao_indica_arme = StringField(
        "Termos de resolução que indicam arme (separados por vírgula)",
        validators=[DataRequired()],
    )
    atend_horas_primeira_execucao = IntegerField(
        "Primeira execução: horas para trás",
        validators=[DataRequired(), NumberRange(min=1, max=720)],
    )
    atend_horas_arme_posterior = IntegerField(
        "Aceitar arme até (horas depois do evento)",
        validators=[DataRequired(), NumberRange(min=1, max=72)],
    )

    # Relatório de Disparos (B.5)
    disp_horas_primeira_execucao = IntegerField(
        "Primeira execução: horas para trás",
        validators=[DataRequired(), NumberRange(min=1, max=720)],
    )
    disp_limite_recorrente = IntegerField(
        "Disparos para virar 'RECORRENTE'",
        validators=[DataRequired(), NumberRange(min=2, max=500)],
    )
    disp_ignorar_zonas = StringField(
        "Ignorar zonas contendo (separados por vírgula)", validators=[DataRequired()]
    )

    # Relatório de Disparos Geral (fim de semana)
    dispg_limite_recorrente = IntegerField(
        "Disparos para virar 'RECORRENTE'",
        validators=[DataRequired(), NumberRange(min=2, max=1000)],
    )
    dispg_grupo_villefort = StringField(
        "Grupo Villefort — nomes contendo (separados por vírgula)", validators=[DataRequired()]
    )
    dispg_grupo_super_nosso = StringField(
        "Grupo Super Nosso — nomes contendo (separados por vírgula)", validators=[DataRequired()]
    )


class TelegramForm(FlaskForm):
    bot_token = StringField("Token do bot", validators=[Optional(), Length(max=200)])
    chat_id = StringField("Chat ID", validators=[Optional(), Length(max=64)])


class BotTecnicoForm(FlaskForm):
    ativado = BooleanField("Bot ligado (responde comandos no Telegram)")
    tecnicos_ids = StringField(
        "IDs de técnicos autorizados (separados por vírgula)",
        validators=[Optional(), Length(max=500)],
    )
    relatorio_dias_padrao = IntegerField(
        "Relatório: dias padrão", validators=[DataRequired(), NumberRange(min=1, max=365)]
    )
    relatorio_codigos = StringField(
        "Relatório: códigos de evento", validators=[DataRequired(), Length(max=200)]
    )
    cooldown_segundos = IntegerField(
        "Cooldown por técnico (segundos)",
        validators=[DataRequired(), NumberRange(min=0, max=600)],
    )
