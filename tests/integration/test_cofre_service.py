import pytest

from app.extensions import db
from app.models.audit import AuditLog
from app.models.cofre import Segredo
from app.services import cofre_service

SENHA_OPERADOR = "senha-forte-123"  # mesma senha fixa da fixture _criar_usuario


def _criar(usuario, config, **overrides):
    dados = {
        "titulo": "DVR Loja Centro",
        "categoria": "camera",
        "login": "admin",
        "senha": "S3nhaForte!123",
        "url": "192.168.0.10",
        "notas": None,
        "nivel": "equipe",
        "user_id": usuario.id,
        "config": config,
    }
    dados.update(overrides)
    segredo = cofre_service.criar(**dados)
    db.session.commit()
    return segredo


# ---------- cifra ida-e-volta ----------


def test_senha_fica_cifrada_no_banco(app, admin_user):
    segredo = _criar(admin_user, app.config)
    assert "S3nhaForte!123" not in segredo.senha_cifrada
    assert cofre_service.decifrar(segredo.senha_cifrada, config=app.config) == "S3nhaForte!123"


def test_notas_tambem_ficam_cifradas(app, admin_user):
    segredo = _criar(admin_user, app.config, notas="ponto de acesso no fundo da loja")
    assert "fundo da loja" not in segredo.notas_cifradas
    assert (
        cofre_service.decifrar(segredo.notas_cifradas, config=app.config)
        == "ponto de acesso no fundo da loja"
    )


def test_chave_do_cofre_e_isolada_da_chave_geral(app, admin_user):
    """ENCRYPTION_KEY e VAULT_ENCRYPTION_KEY são chaves DIFERENTES (ver
    TestingConfig) — decifrar com a errada tem que falhar, não vazar."""
    segredo = _criar(admin_user, app.config)
    config_com_chave_errada = dict(app.config)
    config_com_chave_errada["VAULT_ENCRYPTION_KEY"] = app.config["ENCRYPTION_KEY"]
    with pytest.raises(cofre_service.CofreDecifraError):
        cofre_service.decifrar(segredo.senha_cifrada, config=config_com_chave_errada)


def test_sem_chave_configurada_levanta_erro_amigavel(app, admin_user):
    segredo = _criar(admin_user, app.config)
    config_sem_chave = dict(app.config)
    config_sem_chave["VAULT_ENCRYPTION_KEY"] = None
    with pytest.raises(cofre_service.CofreSemChaveError):
        cofre_service.decifrar(segredo.senha_cifrada, config=config_sem_chave)


# ---------- listar / filtro por papel ----------


def test_operador_nao_ve_item_restrito_na_listagem(app, admin_user, operador_user):
    _criar(admin_user, app.config, titulo="Equipe A", nivel="equipe")
    _criar(admin_user, app.config, titulo="Restrito B", nivel="restrito")

    titulos_admin = {s.titulo for s in cofre_service.listar(usuario=admin_user)}
    titulos_operador = {s.titulo for s in cofre_service.listar(usuario=operador_user)}

    assert titulos_admin == {"Equipe A", "Restrito B"}
    assert titulos_operador == {"Equipe A"}


def test_listar_filtra_por_busca_e_categoria(app, admin_user):
    _criar(admin_user, app.config, titulo="DVR Loja Centro", categoria="camera")
    _criar(admin_user, app.config, titulo="Roteador Loja Centro", categoria="roteador")
    _criar(admin_user, app.config, titulo="E-mail Comercial", categoria="email")

    resultado = cofre_service.listar(usuario=admin_user, busca="Loja Centro")
    assert {s.titulo for s in resultado} == {"DVR Loja Centro", "Roteador Loja Centro"}

    resultado_categoria = cofre_service.listar(usuario=admin_user, categoria="email")
    assert [s.titulo for s in resultado_categoria] == ["E-mail Comercial"]


# ---------- obter_ou_negar ----------


def test_obter_ou_negar_404_quando_nao_existe(app, admin_user):
    with pytest.raises(cofre_service.CofreNaoEncontradoError):
        cofre_service.obter_ou_negar(999999, usuario=admin_user)


def test_obter_ou_negar_barra_operador_em_item_restrito(app, admin_user, operador_user):
    segredo = _criar(admin_user, app.config, nivel="restrito")
    with pytest.raises(cofre_service.CofreAcessoNegadoError):
        cofre_service.obter_ou_negar(segredo.id, usuario=operador_user)

    # admin continua acessando normalmente
    assert cofre_service.obter_ou_negar(segredo.id, usuario=admin_user).id == segredo.id


# ---------- revelar (reautenticação + auditoria) ----------


def test_revelar_com_reautenticacao_correta_devolve_senha_e_audita(app, admin_user):
    segredo = _criar(admin_user, app.config)

    senha = cofre_service.revelar(
        segredo, usuario=admin_user, senha_reautenticacao="senha-forte-123", config=app.config
    )
    db.session.commit()

    assert senha == "S3nhaForte!123"
    evento = AuditLog.query.filter_by(action="cofre_senha_revelada").first()
    assert evento is not None
    assert evento.result == "success"
    assert evento.details["segredo_id"] == segredo.id
    assert evento.details["titulo"] == "DVR Loja Centro"
    assert "senha" not in evento.details
    assert "S3nhaForte!123" not in str(evento.details)


def test_revelar_com_reautenticacao_errada_falha_e_audita_sem_revelar(app, admin_user):
    segredo = _criar(admin_user, app.config)

    with pytest.raises(cofre_service.CofreReautenticacaoInvalidaError):
        cofre_service.revelar(
            segredo, usuario=admin_user, senha_reautenticacao="senha-errada", config=app.config
        )
    db.session.commit()

    evento = AuditLog.query.filter_by(action="cofre_senha_revelada").first()
    assert evento is not None
    assert evento.result == "failure"
    assert "S3nhaForte!123" not in str(evento.details)


def test_operador_nao_revela_item_restrito(app, admin_user, operador_user):
    segredo = _criar(admin_user, app.config, nivel="restrito")
    with pytest.raises(cofre_service.CofreAcessoNegadoError):
        cofre_service.revelar(
            segredo, usuario=operador_user, senha_reautenticacao=SENHA_OPERADOR, config=app.config
        )


# ---------- criar / atualizar / excluir ----------


def test_atualizar_com_senha_vazia_mantem_senha_atual(app, admin_user):
    segredo = _criar(admin_user, app.config)
    original = segredo.senha_cifrada

    cofre_service.atualizar(
        segredo,
        titulo="DVR Loja Centro (renomeado)",
        categoria="camera",
        login="admin",
        senha="",
        url="192.168.0.10",
        notas=None,
        nivel="equipe",
        user_id=admin_user.id,
        config=app.config,
    )
    db.session.commit()

    assert segredo.senha_cifrada == original
    assert segredo.titulo == "DVR Loja Centro (renomeado)"


def test_atualizar_com_senha_nova_recifra(app, admin_user):
    segredo = _criar(admin_user, app.config)

    cofre_service.atualizar(
        segredo,
        titulo=segredo.titulo,
        categoria=segredo.categoria,
        login=segredo.login,
        senha="OutraSenha!456",
        url=segredo.url,
        notas=None,
        nivel=segredo.nivel,
        user_id=admin_user.id,
        config=app.config,
    )
    db.session.commit()

    assert cofre_service.decifrar(segredo.senha_cifrada, config=app.config) == "OutraSenha!456"


def test_excluir_remove_do_banco(app, admin_user):
    segredo = _criar(admin_user, app.config)
    segredo_id = segredo.id
    cofre_service.excluir(segredo)
    db.session.commit()
    assert db.session.get(Segredo, segredo_id) is None
