from app.models import User


def test_seed_admin_creates_admin_user(app):
    runner = app.test_cli_runner()

    result = runner.invoke(
        args=["seed-admin"], input="admin\nsenha-forte-123\nsenha-forte-123\n"
    )

    assert result.exit_code == 0, result.output
    user = User.query.filter_by(username="admin").one()
    assert user.role == "admin"
    assert user.active is True


def test_seed_admin_rejects_mismatched_passwords(app):
    runner = app.test_cli_runner()

    result = runner.invoke(
        args=["seed-admin"], input="admin\nsenha-forte-123\noutra-senha\n"
    )

    assert result.exit_code != 0
    assert User.query.filter_by(username="admin").first() is None
