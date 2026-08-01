from flask_wtf import FlaskForm
from wtforms import IntegerField, StringField
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class ConfiguracaoBiForm(FlaskForm):
    janela_dias = IntegerField(
        "Janela antes/depois (dias)", validators=[DataRequired(), NumberRange(min=1, max=90)]
    )
    limiar_melhora = IntegerField(
        "Limiar de melhora (%)", validators=[DataRequired(), NumberRange(min=1, max=100)]
    )
    limiar_piora = IntegerField(
        "Limiar de piora (%)", validators=[DataRequired(), NumberRange(min=1, max=100)]
    )
    tipos_intervencao = StringField(
        "Tipos de tarefa que contam (taskType, separados por vírgula)",
        validators=[Optional(), Length(max=500)],
    )
    visitas_para_cronico = IntegerField(
        "Visitas mínimas para virar crônico", validators=[DataRequired(), NumberRange(min=2, max=50)]
    )
    periodo_padrao_dias = IntegerField(
        "Período padrão de análise (dias)", validators=[DataRequired(), NumberRange(min=1, max=730)]
    )
    amostra_minima_tecnico = IntegerField(
        "Amostra mínima por técnico (aviso no ranking)",
        validators=[DataRequired(), NumberRange(min=1, max=200)],
    )
