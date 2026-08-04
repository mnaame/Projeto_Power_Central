"""Cofre de Senhas — gerador de senha forte e medidor de força. Lógica
pura (sem I/O); cifra/decifra e persistência ficam em
`services/cofre_service.py`.
"""

from __future__ import annotations

import re
import secrets
import string

TAMANHO_PADRAO = 20
TAMANHO_MINIMO = 8

# Excluídos por padrão do gerador — parecidos demais entre si para digitar
# ou ler à mão (ex.: DVR de loja, onde alguém copia a senha para um papel).
_AMBIGUOS = "Il1O0"
_SIMBOLOS = "!@#$%^&*()-_=+"

FRACA = "fraca"
MEDIA = "media"
FORTE = "forte"
MUITO_FORTE = "muito_forte"


def _sem_ambiguos(alfabeto: str) -> str:
    return "".join(c for c in alfabeto if c not in _AMBIGUOS)


def gerar_senha(*, tamanho: int = TAMANHO_PADRAO, excluir_ambiguos: bool = True) -> str:
    """Senha aleatória com `secrets` (não `random` — não é seguro para
    segredos). Garante ao menos uma letra minúscula, uma maiúscula, um
    dígito e um símbolo."""
    tamanho = max(tamanho, TAMANHO_MINIMO)

    minusculas = string.ascii_lowercase
    maiusculas = string.ascii_uppercase
    digitos = string.digits
    if excluir_ambiguos:
        minusculas = _sem_ambiguos(minusculas)
        maiusculas = _sem_ambiguos(maiusculas)
        digitos = _sem_ambiguos(digitos)

    alfabeto = minusculas + maiusculas + digitos + _SIMBOLOS
    obrigatorios = [
        secrets.choice(minusculas),
        secrets.choice(maiusculas),
        secrets.choice(digitos),
        secrets.choice(_SIMBOLOS),
    ]
    resto = [secrets.choice(alfabeto) for _ in range(tamanho - len(obrigatorios))]
    caracteres = obrigatorios + resto

    # Fisher-Yates com `secrets` — random.shuffle não é seguro para isto.
    for i in range(len(caracteres) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        caracteres[i], caracteres[j] = caracteres[j], caracteres[i]

    return "".join(caracteres)


def forca_senha(senha: str) -> str:
    """Heurística simples (variedade de categoria + tamanho) — não é um
    estimador científico, só o suficiente para sinalizar "curta demais"/
    "só um tipo de caractere" na tela de cadastro. Nunca usado como trava
    de segurança, só de UI."""
    if not senha or len(senha) < TAMANHO_MINIMO:
        return FRACA

    categorias = sum(
        (
            bool(re.search(r"[a-z]", senha)),
            bool(re.search(r"[A-Z]", senha)),
            bool(re.search(r"\d", senha)),
            bool(re.search(r"[^\w\s]", senha)),
        )
    )
    pontos = categorias + (len(senha) >= 12) + (len(senha) >= 16)

    if pontos <= 2:
        return FRACA
    if pontos == 3:
        return MEDIA
    if pontos == 4:
        return FORTE
    return MUITO_FORTE
