"""Cofre de Senhas — cifra/decifra (Fernet, `VAULT_ENCRYPTION_KEY` dedicada,
separada da `ENCRYPTION_KEY` geral), CRUD, filtro por papel e a rota mais
sensível do módulo: revelar (reautentica, decifra, audita — sempre, mesmo
quando a reautenticação falha). A senha nunca aparece em `details` de
auditoria, nunca em log, nunca fora do momento exato de revelar.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.extensions import db
from app.models.cofre import Segredo
from app.security import verify_password
from app.services import audit_service


class CofreError(Exception):
    """Base dos erros do cofre."""


class CofreSemChaveError(CofreError):
    """VAULT_ENCRYPTION_KEY não configurada."""


class CofreDecifraError(CofreError):
    """A cifra não bateu com a chave atual (chave errada/trocada)."""


class CofreNaoEncontradoError(CofreError):
    """Id de segredo que não existe."""


class CofreAcessoNegadoError(CofreError):
    """Usuário sem permissão para este item (operador tentando acessar
    nivel='restrito' por id direto)."""


class CofreReautenticacaoInvalidaError(CofreError):
    """A senha de confirmação (reautenticação) não bateu com a do usuário."""


def _fernet(config) -> Fernet:
    chave = config["VAULT_ENCRYPTION_KEY"]
    if not chave:
        raise CofreSemChaveError(
            "VAULT_ENCRYPTION_KEY não configurada — veja docs/OPERACAO.md."
        )
    return Fernet(chave.encode() if isinstance(chave, str) else chave)


def cifrar(texto: str, *, config) -> str:
    return _fernet(config).encrypt(texto.encode()).decode()


def decifrar(texto_cifrado: str, *, config) -> str:
    try:
        return _fernet(config).decrypt(texto_cifrado.encode()).decode()
    except InvalidToken as exc:
        raise CofreDecifraError(
            "Não foi possível decifrar — confira a VAULT_ENCRYPTION_KEY."
        ) from exc


def _pode_ver(segredo: Segredo, usuario) -> bool:
    return usuario.is_admin or segredo.nivel == "equipe"


def listar(*, usuario, busca: str = "", categoria: str = "") -> list[Segredo]:
    """Filtra `nivel='equipe'` para quem não é admin já na query — nunca
    busca tudo e filtra depois na tela."""
    query = Segredo.query
    if not usuario.is_admin:
        query = query.filter(Segredo.nivel == "equipe")
    if busca:
        padrao = f"%{busca}%"
        query = query.filter(
            db.or_(
                Segredo.titulo.ilike(padrao),
                Segredo.login.ilike(padrao),
                Segredo.url.ilike(padrao),
            )
        )
    if categoria:
        query = query.filter(Segredo.categoria == categoria)
    return query.order_by(Segredo.titulo).all()


def obter_ou_negar(segredo_id: int, *, usuario) -> Segredo:
    """Toda rota que recebe um id de segredo direto na URL passa por aqui
    — mesma disciplina de `roles_required`, só que por registro em vez de
    por rota inteira (um operador não pode contornar o nível "restrito"
    só por saber o id)."""
    segredo = db.session.get(Segredo, segredo_id)
    if segredo is None:
        raise CofreNaoEncontradoError()
    if not _pode_ver(segredo, usuario):
        raise CofreAcessoNegadoError()
    return segredo


def criar(
    *,
    titulo: str,
    categoria: str,
    login: str | None,
    senha: str,
    url: str | None,
    notas: str | None,
    nivel: str,
    user_id: int | None,
    config,
    expira_em=None,
) -> Segredo:
    segredo = Segredo(
        titulo=titulo.strip(),
        categoria=categoria or "outro",
        login=(login or "").strip() or None,
        senha_cifrada=cifrar(senha, config=config),
        url=(url or "").strip() or None,
        notas_cifradas=cifrar(notas, config=config) if notas else None,
        nivel=nivel,
        criado_por_user_id=user_id,
        atualizado_por_user_id=user_id,
        expira_em=expira_em,
    )
    db.session.add(segredo)
    db.session.flush()
    return segredo


def atualizar(
    segredo: Segredo,
    *,
    titulo: str,
    categoria: str,
    login: str | None,
    senha: str | None,
    url: str | None,
    notas: str | None,
    nivel: str,
    user_id: int | None,
    config,
    expira_em=None,
) -> Segredo:
    """Senha vazia = "não trocar" (mesma UX de qualquer formulário de
    credencial que já existe no site)."""
    segredo.titulo = titulo.strip()
    segredo.categoria = categoria or "outro"
    segredo.login = (login or "").strip() or None
    if senha:
        segredo.senha_cifrada = cifrar(senha, config=config)
    segredo.url = (url or "").strip() or None
    segredo.notas_cifradas = cifrar(notas, config=config) if notas else None
    segredo.nivel = nivel
    segredo.atualizado_por_user_id = user_id
    segredo.expira_em = expira_em
    return segredo


def excluir(segredo: Segredo) -> None:
    db.session.delete(segredo)


def notas_em_claro(segredo: Segredo, *, config) -> str:
    """Notas decifradas, para preencher o formulário de edição.

    Ao contrário da senha, as notas **não** exigem reautenticação: elas são
    contexto do item (por onde entrar, com quem falar), e quem chegou na
    tela de edição já passou pelo controle de nível em `obter_ou_negar`.
    Precisam voltar ao formulário porque, sem isso, editar qualquer outro
    campo apagava a nota — o `atualizar` grava o que veio do formulário, e
    o formulário vinha vazio."""
    if not segredo.notas_cifradas:
        return ""
    return decifrar(segredo.notas_cifradas, config=config)


def revelar(segredo: Segredo, *, usuario, senha_reautenticacao: str, config) -> str:
    """Confere a senha do PRÓPRIO usuário de novo (reautenticação), decifra
    e audita — sempre, mesmo em falha de reautenticação. A senha nunca
    entra no `details` da auditoria."""
    if not _pode_ver(segredo, usuario):
        # Defesa em profundidade — a rota já barra isso via obter_ou_negar
        # antes de chegar aqui; nunca deveria disparar na prática.
        raise CofreAcessoNegadoError()

    if not verify_password(usuario.password_hash, senha_reautenticacao):
        audit_service.registrar(
            action="cofre_senha_revelada",
            result="failure",
            user=usuario,
            details={
                "segredo_id": segredo.id,
                "titulo": segredo.titulo,
                "motivo": "reautenticacao_invalida",
            },
        )
        raise CofreReautenticacaoInvalidaError()

    senha = decifrar(segredo.senha_cifrada, config=config)
    audit_service.registrar(
        action="cofre_senha_revelada",
        result="success",
        user=usuario,
        details={
            "segredo_id": segredo.id,
            "titulo": segredo.titulo,
            "categoria": segredo.categoria,
        },
    )
    return senha
