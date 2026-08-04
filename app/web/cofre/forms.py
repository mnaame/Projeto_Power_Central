from flask_wtf import FlaskForm
from wtforms import DateField, PasswordField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional

from app.models.cofre import CATEGORIAS, NIVEIS

CATEGORIA_LABELS = {
    "camera": "Câmera/DVR",
    "roteador": "Roteador/Rede",
    "plataforma": "Plataforma/Sistema",
    "email": "E-mail",
    "cliente": "Acesso de cliente",
    "outro": "Outro",
}
NIVEL_LABELS = {"equipe": "Equipe (todos veem)", "restrito": "Restrito (só admin)"}


class SegredoForm(FlaskForm):
    titulo = StringField("Título", validators=[DataRequired(), Length(max=200)])
    categoria = SelectField(
        "Categoria", choices=[(c, CATEGORIA_LABELS[c]) for c in CATEGORIAS]
    )
    login = StringField("Login/usuário", validators=[Optional(), Length(max=200)])
    # Sem DataRequired de propósito: vazio na edição = "não trocar a senha"
    # (checado na rota); na criação, a rota exige preenchido.
    senha = PasswordField("Senha", validators=[Optional(), Length(max=500)])
    url = StringField("URL/endereço", validators=[Optional(), Length(max=500)])
    notas = TextAreaField("Notas", validators=[Optional(), Length(max=4000)])
    nivel = SelectField("Nível", choices=[(n, NIVEL_LABELS[n]) for n in NIVEIS])
    expira_em = DateField("Lembrete de troca (opcional)", validators=[Optional()])
