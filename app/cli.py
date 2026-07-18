import getpass
from datetime import datetime, timedelta, timezone

import click

from app.domain.dates import FUSO_HORARIO
from app.extensions import db
from app.models.user import User
from app.security import hash_password


def _contas_exemplo() -> list[dict]:
    """Massa de dados sintética para `flask collect --dry-run` — cobre os
    três casos centrais da regra de negócio (seção 6): sem comunicação
    (PTB não comprova), falso positivo (TST recente comprova) e sem
    comunicação por TST fora da janela."""
    agora = datetime.now(FUSO_HORARIO)

    def _fmt(dt: datetime) -> str:
        return dt.strftime("%m/%d/%Y %I:%M:%S %p")

    falha_desde = _fmt(agora - timedelta(days=2))
    recente = _fmt(agora - timedelta(minutes=10))
    ha_6_horas = _fmt(agora - timedelta(hours=6))

    return [
        {
            "cue_ncuenta": "1001",
            "cue_cnombre": "Cliente Exemplo Mudo (PTB)",
            "sta_ncuentaenfallodetst": "1",
            "sta_tEnFalloDeTSTDesde": falha_desde,
            "cue_cUltimaAlarmaRecibida": "PTB",
            "cue_dFechaUltimaAlarmaRecibida": recente,
        },
        {
            "cue_ncuenta": "1002",
            "cue_cnombre": "Cliente Exemplo Falso Positivo (TST recente)",
            "sta_ncuentaenfallodetst": "1",
            "sta_tEnFalloDeTSTDesde": falha_desde,
            "cue_cUltimaAlarmaRecibida": "TST",
            "cue_dFechaUltimaAlarmaRecibida": recente,
        },
        {
            "cue_ncuenta": "1003",
            "cue_cnombre": "Cliente Exemplo Mudo (TST fora da janela)",
            "sta_ncuentaenfallodetst": "1",
            "sta_tEnFalloDeTSTDesde": falha_desde,
            "cue_cUltimaAlarmaRecibida": "TST",
            "cue_dFechaUltimaAlarmaRecibida": ha_6_horas,
        },
    ]


class _ClienteSoftGuardExemplo:
    def buscar_contas_em_falha_tst(self, **kwargs):
        return _contas_exemplo()


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

    @app.cli.command("generate-key")
    def generate_key() -> None:
        """Gera uma chave Fernet para ENCRYPTION_KEY (.env)."""
        from cryptography.fernet import Fernet

        click.echo(Fernet.generate_key().decode())

    @app.cli.command("collect")
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Usa dados de exemplo em vez de consultar o portal SoftGuard real.",
    )
    def collect(dry_run: bool) -> None:
        """Executa um ciclo do coletor manualmente (login -> consulta ->
        classificação -> persistência -> alertas)."""
        from app.services.collector import executar_ciclo

        softguard_client = _ClienteSoftGuardExemplo() if dry_run else None
        cycle = executar_ciclo(config=app.config, source="manual", softguard_client=softguard_client)

        click.echo(
            f"Ciclo #{cycle.id} finalizado (status={cycle.status}) — "
            f"em_falha_tst={cycle.total_em_falha_tst}, "
            f"sem_comunicacao={cycle.total_sem_comunicacao}, "
            f"falso_positivo={cycle.total_falso_positivo}"
        )
        if cycle.status == "error":
            click.echo(f"Erro: {cycle.error_message}")
            raise SystemExit(1)
