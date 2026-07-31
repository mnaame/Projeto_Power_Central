from flask_wtf import FlaskForm
from wtforms import IntegerField, StringField
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class ConfiguracaoTecnicoForm(FlaskForm):
    nome_padrao = StringField(
        "Técnico padrão (nome ou id)",
        validators=[Optional(), Length(max=200)],
    )
    codigos_padrao = StringField(
        "Códigos de evento padrão",
        validators=[DataRequired(), Length(max=500)],
    )
    periodo_dias_padrao = IntegerField(
        "Período padrão do histórico (dias)",
        validators=[DataRequired(), NumberRange(min=1, max=365)],
    )
