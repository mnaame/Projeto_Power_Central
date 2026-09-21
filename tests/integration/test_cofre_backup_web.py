"""Backup do Cofre — o teste que importa é o de desastre: gerar o arquivo,
perder o cofre E a chave, e recuperar tudo numa instalação com chave nova.
"""

import json
from io import BytesIO

import pytest

from app.domain import cofre_backup as dom_backup
from app.extensions import db
from app.models.audit import AuditLog
from app.models.cofre import Segredo
from app.services import cofre_service

SENHA_ADMIN = "senha-forte-123"  # mesma do conftest
SENHA_BACKUP = "frase-longa-de-backup-2026"
# Chave Fernet válida, diferente da de testes — simula a instalação nova.
OUTRA_CHAVE = "Zt8jQnKk1Yq0vOaW7cLdRb3sXy5uHgE2pMiNfT4oJ9A="


@pytest.fixture(autouse=True)
def _kdf_rapido(monkeypatch):
    """600 mil iterações são certas em produção e um desperdício na suíte —
    o que se testa aqui é o fluxo, não o custo da derivação."""
    monkeypatch.setattr(dom_backup, "ITERACOES", 1000)


def _criar(app, *, titulo, senha, nivel="equipe", notas=None):
    segredo = cofre_service.criar(
        titulo=titulo,
        categoria="camera",
        login="admin",
        senha=senha,
        url="http://192.168.0.10",
        notas=notas,
        nivel=nivel,
        user_id=None,
        config=app.config,
    )
    db.session.commit()
    return segredo


def _exportar(admin_client, *, follow_redirects=False, **extra):
    dados = {
        "senha_backup": SENHA_BACKUP,
        "senha_backup_confirmacao": SENHA_BACKUP,
        "senha_reautenticacao": SENHA_ADMIN,
    }
    dados.update(extra)
    return admin_client.post(
        "/cofre/backup/exportar", data=dados, follow_redirects=follow_redirects
    )


def _enviar(admin_client, pacote: bytes, *, follow_redirects=False, **extra):
    dados = {
        "arquivo": (BytesIO(pacote), "cofre_backup.json"),
        "senha_backup": SENHA_BACKUP,
        "senha_reautenticacao": SENHA_ADMIN,
    }
    dados.update(extra)
    return admin_client.post(
        "/cofre/backup/restaurar",
        data=dados,
        content_type="multipart/form-data",
        follow_redirects=follow_redirects,
    )


# ---------- permissões ----------


def test_backup_exige_login(client):
    assert client.get("/cofre/backup").status_code == 302


def test_operador_nao_acessa_backup(operador_client):
    """O arquivo leva o cofre inteiro, itens restritos incluídos."""
    assert operador_client.get("/cofre/backup").status_code == 403


def test_operador_nao_exporta(operador_client):
    assert operador_client.post("/cofre/backup/exportar", data={}).status_code == 403


def test_operador_nao_restaura(operador_client):
    assert operador_client.post("/cofre/backup/restaurar", data={}).status_code == 403


def test_admin_acessa_a_tela(admin_client):
    assert admin_client.get("/cofre/backup").status_code == 200


# ---------- exportar ----------


def test_exporta_o_cofre_cifrado(app, admin_client):
    _criar(app, titulo="DVR Loja", senha="SENHA-DO-DVR", notas="NOTA-SECRETA")

    resposta = _exportar(admin_client)

    assert resposta.status_code == 200
    assert "cofre_backup_" in resposta.headers["Content-Disposition"]

    corpo = resposta.data.decode()
    assert "SENHA-DO-DVR" not in corpo
    assert "NOTA-SECRETA" not in corpo
    assert json.loads(corpo)["formato"] == dom_backup.FORMATO


def test_exportar_com_senha_de_acesso_errada_nao_gera_arquivo(app, admin_client):
    _criar(app, titulo="DVR", senha="x")

    resposta = _exportar(admin_client, senha_reautenticacao="errada", follow_redirects=True)

    assert b"senha est\xc3\xa1 incorreta" in resposta.data
    assert AuditLog.query.filter_by(action="cofre_backup_exportado", result="failure").count() == 1


def test_senhas_do_backup_diferentes_nao_geram_arquivo(app, admin_client):
    _criar(app, titulo="DVR", senha="x")

    resposta = _exportar(
        admin_client, senha_backup_confirmacao="outra-frase-diferente", follow_redirects=True
    )

    assert "não são iguais".encode() in resposta.data


def test_senha_de_backup_curta_e_recusada(app, admin_client):
    _criar(app, titulo="DVR", senha="x")

    resposta = _exportar(
        admin_client, senha_backup="curta", senha_backup_confirmacao="curta",
        follow_redirects=True,
    )

    assert b"pelo menos" in resposta.data


def test_exportacao_auditada_sem_senha_nenhuma(app, admin_client):
    _criar(app, titulo="DVR", senha="SENHA-DO-DVR")

    _exportar(admin_client)

    entrada = AuditLog.query.filter_by(action="cofre_backup_exportado", result="success").one()
    assert len(entrada.action) <= 48
    assert entrada.details == {"itens": 1}
    assert "SENHA-DO-DVR" not in str(entrada.details)
    assert SENHA_BACKUP not in str(entrada.details)


# ---------- conferir ----------


def test_conferir_nao_altera_nada(app, admin_client):
    _criar(app, titulo="DVR", senha="x")
    pacote = _exportar(admin_client).data
    Segredo.query.delete()
    db.session.commit()

    resposta = _enviar(admin_client, pacote, modo="conferir", follow_redirects=True)

    assert b"Arquivo v\xc3\xa1lido" in resposta.data
    assert Segredo.query.count() == 0  # conferir NÃO restaura


def test_conferir_com_senha_errada_avisa(app, admin_client):
    _criar(app, titulo="DVR", senha="x")
    pacote = _exportar(admin_client).data

    resposta = _enviar(
        admin_client, pacote, modo="conferir", senha_backup="senha-de-backup-errada",
        follow_redirects=True,
    )

    assert b"Senha incorreta" in resposta.data


def test_arquivo_que_nao_e_backup_avisa_sem_derrubar(admin_client):
    resposta = _enviar(admin_client, b"qualquer coisa", modo="conferir", follow_redirects=True)

    assert resposta.status_code == 200
    assert b"n\xc3\xa3o \xc3\xa9 um backup" in resposta.data


def test_restaurar_sem_arquivo_avisa(admin_client):
    resposta = admin_client.post(
        "/cofre/backup/restaurar", data={"senha_backup": SENHA_BACKUP},
        content_type="multipart/form-data", follow_redirects=True,
    )

    assert b"Escolha o arquivo" in resposta.data


# ---------- restaurar ----------


def test_desastre_completo_cofre_e_chave_perdidos(app, admin_client):
    """O cenário que justifica a feature inteira: o servidor se perde com
    a VAULT_ENCRYPTION_KEY junto. O backup precisa abrir numa instalação
    nova, com chave nova — se ele dependesse da chave antiga, seria um
    arquivo inútil exatamente no dia em que é a única cópia."""
    _criar(app, titulo="DVR Loja", senha="SENHA-DO-DVR", notas="entrar pela porta 8080")
    _criar(app, titulo="Roteador", senha="SENHA-DO-ROTEADOR", nivel="restrito")
    pacote = _exportar(admin_client).data

    # Servidor novo: cofre vazio e OUTRA chave de cifragem.
    Segredo.query.delete()
    db.session.commit()
    app.config["VAULT_ENCRYPTION_KEY"] = OUTRA_CHAVE

    resposta = _enviar(admin_client, pacote, modo="restaurar", follow_redirects=True)
    assert b"Restaura\xc3\xa7\xc3\xa3o conclu\xc3\xadda" in resposta.data

    dvr = Segredo.query.filter_by(titulo="DVR Loja").one()
    assert cofre_service.decifrar(dvr.senha_cifrada, config=app.config) == "SENHA-DO-DVR"
    assert cofre_service.notas_em_claro(dvr, config=app.config) == "entrar pela porta 8080"

    roteador = Segredo.query.filter_by(titulo="Roteador").one()
    assert cofre_service.decifrar(roteador.senha_cifrada, config=app.config) == "SENHA-DO-ROTEADOR"
    assert roteador.nivel == "restrito"  # o nível volta junto


def test_restauracao_nao_sobrescreve_por_padrao(app, admin_client):
    """Restaurar por engano em cima de um cofre vivo é pior do que
    restaurar de menos: o que foi sobrescrito não volta."""
    _criar(app, titulo="DVR Loja", senha="SENHA-ANTIGA")
    pacote = _exportar(admin_client).data

    segredo = Segredo.query.filter_by(titulo="DVR Loja").one()
    cofre_service.atualizar(
        segredo, titulo="DVR Loja", categoria="camera", login="admin",
        senha="SENHA-NOVA-TROCADA", url=None, notas=None, nivel="equipe",
        user_id=None, config=app.config,
    )
    db.session.commit()

    _enviar(admin_client, pacote, modo="restaurar", follow_redirects=True)

    atual = Segredo.query.filter_by(titulo="DVR Loja").one()
    assert cofre_service.decifrar(atual.senha_cifrada, config=app.config) == "SENHA-NOVA-TROCADA"
    assert Segredo.query.count() == 1


def test_substituir_marcado_sobrescreve(app, admin_client):
    _criar(app, titulo="DVR Loja", senha="SENHA-DO-BACKUP")
    pacote = _exportar(admin_client).data

    segredo = Segredo.query.filter_by(titulo="DVR Loja").one()
    cofre_service.atualizar(
        segredo, titulo="DVR Loja", categoria="camera", login="admin",
        senha="SENHA-NOVA-TROCADA", url=None, notas=None, nivel="equipe",
        user_id=None, config=app.config,
    )
    db.session.commit()

    _enviar(admin_client, pacote, modo="restaurar", substituir="on", follow_redirects=True)

    atual = Segredo.query.filter_by(titulo="DVR Loja").one()
    assert cofre_service.decifrar(atual.senha_cifrada, config=app.config) == "SENHA-DO-BACKUP"


def test_restaurar_com_senha_de_acesso_errada_nao_grava(app, admin_client):
    _criar(app, titulo="DVR", senha="x")
    pacote = _exportar(admin_client).data
    Segredo.query.delete()
    db.session.commit()

    resposta = _enviar(
        admin_client, pacote, modo="restaurar", senha_reautenticacao="errada",
        follow_redirects=True,
    )

    assert b"senha est\xc3\xa1 incorreta" in resposta.data
    assert Segredo.query.count() == 0
    assert AuditLog.query.filter_by(action="cofre_backup_restaurado", result="failure").count() == 1


def test_item_sem_senha_e_pulado_sem_derrubar_o_resto(app, admin_client):
    """Arquivo meio corrompido deve restaurar o que dá, não falhar inteiro."""
    pacote = dom_backup.empacotar(
        [
            {"titulo": "Bom", "senha": "vale"},
            {"titulo": "Sem senha", "senha": ""},
            {"titulo": "", "senha": "sem titulo"},
        ],
        senha=SENHA_BACKUP,
        iteracoes=1000,
    )

    _enviar(admin_client, pacote, modo="restaurar", follow_redirects=True)

    assert [s.titulo for s in Segredo.query.all()] == ["Bom"]


def test_restauracao_auditada_com_contadores(app, admin_client):
    _criar(app, titulo="DVR", senha="x")
    pacote = _exportar(admin_client).data
    Segredo.query.delete()
    db.session.commit()

    _enviar(admin_client, pacote, modo="restaurar", follow_redirects=True)

    entrada = AuditLog.query.filter_by(action="cofre_backup_restaurado", result="success").one()
    assert len(entrada.action) <= 48
    assert entrada.details["adicionados"] == 1
    assert entrada.details["ignorados"] == 0
