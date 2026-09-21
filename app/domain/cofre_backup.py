"""Backup do Cofre de Senhas — envelope cifrado por senha. Camada pura.

**Por que não usar a `VAULT_ENCRYPTION_KEY` aqui.** Ela cifra o cofre no
banco, e a documentação já avisa: perdê-la torna as senhas irrecuperáveis.
Um backup cifrado com ela herdaria o mesmo destino — perdeu a chave, perdeu
o banco *e* o backup. Ou seja, justamente o desastre que um backup existe
para evitar.

Por isso o arquivo é cifrado com uma **senha digitada na hora da
exportação**, e carrega dentro de si o sal e os parâmetros de derivação.
Consequência prática: ele se restaura num servidor novo, com chave nova,
sem depender de nada da máquina antiga. Duas contrapartidas, e as duas são
do dono do arquivo: a segurança dele é a força dessa senha (a tela avisa,
sem impedir — ver `TAMANHO_RECOMENDADO`), e **quem esquece a senha perde o
backup**, sem recurso — não há "esqueci minha senha" em cifra de verdade.

Formato (JSON, para poder ser inspecionado sem ferramenta especial):

    {
      "formato": "power-central-cofre-backup",
      "versao": 1,
      "criado_em": "2026-09-21T10:30:00+00:00",
      "itens": 42,                 <- só a CONTAGEM, nunca os dados
      "kdf": {"algoritmo": "pbkdf2-sha256", "iteracoes": ..., "salt": "..."},
      "conteudo": "<token Fernet>"
    }

Os metadados ficam em claro de propósito: dá para conferir quando o backup
foi feito e quantos itens tem sem precisar da senha. Nada além da contagem
sai do envelope cifrado.
"""

from __future__ import annotations

import base64
import json
import secrets
from datetime import datetime, timezone
from typing import Any, Sequence

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

FORMATO = "power-central-cofre-backup"
VERSAO = 1

# PBKDF2-HMAC-SHA256 no patamar recomendado pela OWASP (2023). Custa uma
# fração de segundo numa operação manual e encarece muito a força bruta
# contra o arquivo, que é o único ataque possível contra ele.
ITERACOES = 600_000
TAMANHO_SALT = 16

# Tamanho **recomendado**, não exigido. Existiu aqui uma trava de 12
# caracteres; ela saiu a pedido de quem opera o cofre, e a razão é boa:
# quem guarda o arquivo é quem decide o quanto quer protegê-lo, e uma
# recusa não ensina nada — só impede. O aviso continua na tela, com
# indicador de força ao digitar; o que não existe mais é a recusa.
#
# O único caso ainda barrado é senha **vazia**: cifrar com nada não é
# cifrar, e o arquivo sairia abrível por qualquer um que conheça o formato.
TAMANHO_RECOMENDADO = 12

CAMPOS = (
    "titulo",
    "categoria",
    "login",
    "senha",
    "url",
    "notas",
    "nivel",
    "expira_em",
)


class BackupError(Exception):
    """Base dos erros de backup do cofre."""


class BackupSenhaVaziaError(BackupError):
    """Senha de backup em branco — cifrar com nada é não cifrar."""


class BackupSenhaInvalidaError(BackupError):
    """A senha não abriu o arquivo (ou o arquivo foi corrompido)."""


class BackupFormatoInvalidoError(BackupError):
    """Não é um arquivo de backup do cofre."""


def validar_senha_backup(senha: str) -> None:
    """Não há tamanho mínimo — só não dá para cifrar com nada."""
    if not senha:
        raise BackupSenhaVaziaError(
            "Informe a senha do backup — é ela que protege o arquivo inteiro."
        )


def senha_curta(senha: str) -> bool:
    """Para a tela avisar sem impedir."""
    return 0 < len(senha or "") < TAMANHO_RECOMENDADO


def derivar_chave(senha: str, salt: bytes, *, iteracoes: int | None = None) -> bytes:
    """Senha + sal -> chave Fernet. O sal viaja no envelope: ele não é
    segredo, serve para que dois backups com a mesma senha não produzam a
    mesma chave."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iteracoes or ITERACOES,
    )
    return base64.urlsafe_b64encode(kdf.derive(senha.encode()))


def empacotar(
    itens: Sequence[dict[str, Any]], *, senha: str, iteracoes: int | None = None
) -> bytes:
    """Monta o arquivo de backup já cifrado. `itens` chega em claro (quem
    chama decifrou do cofre) e não sobra em lugar nenhum além do token."""
    validar_senha_backup(senha)

    iteracoes = iteracoes or ITERACOES
    salt = secrets.token_bytes(TAMANHO_SALT)
    chave = derivar_chave(senha, salt, iteracoes=iteracoes)
    corpo = json.dumps(list(itens), ensure_ascii=False).encode()
    token = Fernet(chave).encrypt(corpo)

    envelope = {
        "formato": FORMATO,
        "versao": VERSAO,
        "criado_em": datetime.now(timezone.utc).isoformat(),
        "itens": len(itens),
        "kdf": {
            "algoritmo": "pbkdf2-sha256",
            "iteracoes": iteracoes,
            "salt": base64.b64encode(salt).decode(),
        },
        "conteudo": token.decode(),
    }
    return json.dumps(envelope, ensure_ascii=False, indent=2).encode()


def ler_metadados(conteudo: bytes) -> dict[str, Any]:
    """Cabeçalho do arquivo **sem** precisar da senha — para dizer na tela
    de que data é o backup e quantos itens tem antes de tentar abrir."""
    try:
        envelope = json.loads(conteudo.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupFormatoInvalidoError(
            "Este arquivo não é um backup do cofre (não é um JSON válido)."
        ) from exc

    if not isinstance(envelope, dict) or envelope.get("formato") != FORMATO:
        raise BackupFormatoInvalidoError(
            "Este arquivo não é um backup do cofre da Power Central."
        )
    if envelope.get("versao") != VERSAO:
        raise BackupFormatoInvalidoError(
            f"Backup na versão {envelope.get('versao')!r}; esta instalação "
            f"lê a versão {VERSAO}."
        )
    return envelope


def desempacotar(conteudo: bytes, *, senha: str) -> list[dict[str, Any]]:
    """Abre o arquivo e devolve os itens em claro."""
    envelope = ler_metadados(conteudo)

    kdf = envelope.get("kdf") or {}
    try:
        salt = base64.b64decode(kdf["salt"])
        iteracoes = int(kdf["iteracoes"])
        token = envelope["conteudo"].encode()
    except (KeyError, TypeError, ValueError) as exc:
        raise BackupFormatoInvalidoError(
            "O arquivo de backup está incompleto ou corrompido."
        ) from exc

    chave = derivar_chave(senha or "", salt, iteracoes=iteracoes)
    try:
        corpo = Fernet(chave).decrypt(token)
    except InvalidToken as exc:
        # Fernet é autenticado: senha errada e arquivo adulterado dão o
        # mesmo erro, e não há como distinguir — a mensagem cobre os dois.
        raise BackupSenhaInvalidaError(
            "Senha incorreta, ou o arquivo foi alterado desde que foi gerado."
        ) from exc

    itens = json.loads(corpo.decode())
    if not isinstance(itens, list):
        raise BackupFormatoInvalidoError("Conteúdo do backup em formato inesperado.")
    return itens
