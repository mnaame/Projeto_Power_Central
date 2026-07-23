from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    FloatField,
    IntegerField,
    SelectField,
    StringField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class CredenciaisAuvoForm(FlaskForm):
    api_key = StringField("API Key", validators=[DataRequired(), Length(max=200)])
    api_token = StringField("API Token", validators=[DataRequired(), Length(max=200)])


class ConfiguracaoAuvoForm(FlaskForm):
    criador_id = IntegerField(
        "ID do criador (idUserFrom)", validators=[Optional(), NumberRange(min=1)]
    )
    responsavel_id = IntegerField(
        "ID do responsável (idUserTo)", validators=[Optional(), NumberRange(min=1)]
    )
    atribuir_responsavel = BooleanField("Atribuir a tarefa ao responsável")
    task_type = IntegerField(
        "Tipo de tarefa (taskType)", validators=[Optional(), NumberRange(min=1)]
    )
    priority = SelectField(
        "Prioridade",
        choices=[("1", "1 — baixa"), ("2", "2 — média"), ("3", "3 — alta")],
    )
    cooldown_horas = FloatField(
        "Cooldown entre chamados da mesma conta (horas)",
        validators=[DataRequired(), NumberRange(min=1, max=168)],
    )
    sem_comunicacao_horas_minimas = FloatField(
        "Sem comunicação: horas mínimas antes de abrir",
        validators=[DataRequired(), NumberRange(min=0, max=72)],
    )
    disparos_minimos_tarefa = IntegerField(
        "Disparos: mínimo de disparos válidos para abrir",
        validators=[DataRequired(), NumberRange(min=1, max=500)],
    )
    template_semcom_titulo = StringField(
        "Sem comunicação — título", validators=[DataRequired(), Length(max=300)]
    )
    template_semcom_descricao = TextAreaField(
        "Sem comunicação — descrição", validators=[DataRequired(), Length(max=2000)]
    )
    template_disparos_titulo = StringField(
        "Disparos — título", validators=[DataRequired(), Length(max=300)]
    )
    template_disparos_descricao = TextAreaField(
        "Disparos — descrição", validators=[DataRequired(), Length(max=2000)]
    )


class TestarCriacaoForm(FlaskForm):
    customer_id = IntegerField(
        "ID de cliente Auvo para o teste", validators=[Optional(), NumberRange(min=1)]
    )
