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


class TelegramForm(FlaskForm):
    bot_token = StringField("Token do bot", validators=[Optional(), Length(max=200)])
    chat_id = StringField("Chat ID", validators=[Optional(), Length(max=64)])
