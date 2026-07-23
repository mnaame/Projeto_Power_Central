from app.extensions import db
from app.models.settings import Setting
from app.services import settings_service


def test_defaults_do_modulo_auvo(app):
    assert settings_service.auvo_simulacao() is True  # simulação LIGADA por padrão
    assert settings_service.get_auvo_priority() == 2
    assert settings_service.get_auvo_cooldown_horas() == 12.0
    assert settings_service.get_auvo_sem_comunicacao_horas_minimas() == 3.0
    assert settings_service.get_auvo_disparos_minimos_tarefa() == 5
    assert settings_service.auvo_atribuir_responsavel() is True
    # sem configuração: IDs vazios viram None (e nada de crash)
    assert settings_service.get_auvo_criador_id() is None
    assert settings_service.get_auvo_responsavel_id() is None
    assert settings_service.get_auvo_task_type() is None


def test_templates_padrao_com_placeholders(app):
    titulo = settings_service.get_auvo_template("semcom", "titulo")
    assert "{conta}" in titulo and "{nome}" in titulo
    descricao = settings_service.get_auvo_template("disparos", "descricao")
    assert "{qtd}" in descricao and "{zonas}" in descricao


def test_credenciais_auvo_cifradas_no_banco(app):
    chave = app.config["ENCRYPTION_KEY"]

    assert settings_service.get_auvo_credentials(encryption_key=chave) is None

    settings_service.set_auvo_credentials("minha-key", "meu-token", encryption_key=chave)

    assert settings_service.get_auvo_credentials(encryption_key=chave) == (
        "minha-key",
        "meu-token",
    )
    # o que está gravado no banco NÃO é o valor em claro
    gravado = db.session.get(Setting, "auvo_api_key").value
    assert "minha-key" not in gravado


def test_credenciais_auvo_com_chave_errada_viram_none(app):
    from cryptography.fernet import Fernet

    settings_service.set_auvo_credentials(
        "key", "token", encryption_key=app.config["ENCRYPTION_KEY"]
    )
    outra_chave = Fernet.generate_key().decode()
    assert settings_service.get_auvo_credentials(encryption_key=outra_chave) is None
