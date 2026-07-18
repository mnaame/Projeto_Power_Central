import getpass

import click

from app.extensions import db
from app.models.user import User
from app.security import hash_password


def register_cli(app) -> None:
    @app.cli.command("seed-admin")
    @click.option("--username", prompt=True)
    def seed_admin(username: str) -> None:
        """Cria o primeiro usuário administrador."""
        if User.query.filter_by(username=username).first():
            click.echo(f"Usuário '{username}' já existe.")
            return

        password = getpass.getpass("Senha: ")
        confirm = getpass.getpass("Confirme a senha: ")
        if password != confirm:
            click.echo("Senhas não conferem.")
            raise SystemExit(1)
        if len(password) < 8:
            click.echo("A senha deve ter ao menos 8 caracteres.")
            raise SystemExit(1)

        user = User(
            username=username,
            password_hash=hash_password(password),
            role="admin",
            active=True,
        )
        db.session.add(user)
        db.session.commit()
        click.echo(f"Administrador '{username}' criado com sucesso.")
