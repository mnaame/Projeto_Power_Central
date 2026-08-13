from flask_wtf import FlaskForm
from wtforms import BooleanField, FloatField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class PrepararForm(FlaskForm):
    score_minimo = FloatField(
        "Score mínimo (automático)", validators=[Optional(), NumberRange(min=0, max=1)]
    )
    ids_extra = StringField(
        "IDs Auvo extra — REVISAR/NAO/score baixo marcados na mão (separados por vírgula)",
        validators=[Optional(), Length(max=2000)],
    )


class ConfiguracaoCentralForm(FlaskForm):
    score_minimo = FloatField(
        "Score mínimo (automático)", validators=[DataRequired(), NumberRange(min=0, max=1)]
    )
    auvo_user_request = StringField(
        "ID do usuário do painel (cabeçalho auvo-user-request)",
        validators=[Optional(), Length(max=64)],
    )
    cargo_padrao = StringField("Cargo padrão do contato", validators=[DataRequired(), Length(max=100)])
    pausa_segundos = FloatField(
        "Pausa entre requisições (segundos)", validators=[DataRequired(), NumberRange(min=0, max=60)]
    )
    menu_solicitacoes = BooleanField("Menu Solicitações")
    menu_os = BooleanField("Menu OS")
    menu_orcamento = BooleanField("Menu Orçamento")
    gerar_login_senha = BooleanField(
        "Gerar login/senha nos contatos (deixe desligado até confirmar que a Auvo exige — ver Configuração)"
    )
    whatsapp_ddi = StringField(
        "DDI padrão do WhatsApp", validators=[Optional(), Length(max=4)]
    )
    whatsapp_template = TextAreaField(
        "Mensagem do WhatsApp",
        validators=[DataRequired(), Length(max=4000)],
    )
