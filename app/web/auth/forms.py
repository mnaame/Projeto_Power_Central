from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField
from wtforms.validators import DataRequired


class LoginForm(FlaskForm):
    username = StringField("Usuário", validators=[DataRequired(message="Informe o usuário.")])
    password = PasswordField("Senha", validators=[DataRequired(message="Informe a senha.")])
