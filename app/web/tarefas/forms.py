from flask_wtf import FlaskForm
from wtforms import DateField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional

from app.models.tarefa import HORIZONTES, PRIORIDADES

HORIZONTE_LABELS = {"fixa": "Fixa", "semana": "Semana", "dia": "Dia"}
PRIORIDADE_LABELS = {"baixa": "Baixa", "media": "Média", "alta": "Alta"}


class TarefaForm(FlaskForm):
    """Formulário completo (usado na edição — a adição rápida é um POST
    simples direto na tela, só título + horizonte)."""

    titulo = StringField("Título", validators=[DataRequired(), Length(max=300)])
    descricao = TextAreaField("Descrição", validators=[Optional(), Length(max=4000)])
    horizonte = SelectField(
        "Horizonte", choices=[(h, HORIZONTE_LABELS[h]) for h in HORIZONTES]
    )
    data = DateField("Data", validators=[Optional()])
    prioridade = SelectField(
        "Prioridade", choices=[(p, PRIORIDADE_LABELS[p]) for p in PRIORIDADES]
    )
