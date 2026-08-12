"""Links da Central do Cliente (Auvo) — lógica pura (sem I/O). O cliente
HTTP fica em `integrations/auvo_painel_client.py`; a orquestração
(elegibilidade real contra o banco, criação, auditoria) fica em
`services/central_cliente_service.py`.
"""

from __future__ import annotations

import re
import secrets
from urllib.parse import quote

# Formato CONFIRMADO contra um link real capturado no F12 (ver
# docs/CENTRAL_CLIENTE.md §6, item 1): 8-4-4-4-13 em hexadecimal — não é
# UUID v4 padrão (que seria 8-4-4-4-12). Por isso geramos hex cru por
# grupo (`secrets`, não `uuid.uuid4()`/`random`) em vez de usar o gerador
# de UUID da lib padrão.
_GRUPOS = (8, 4, 4, 4, 13)
_HEX = "0123456789abcdef"


def gerar_identificador() -> str:
    return "-".join("".join(secrets.choice(_HEX) for _ in range(tamanho)) for tamanho in _GRUPOS)


URL_BASE = "https://novomillenium.auvo.com.br/share"


def montar_url(identificador: str) -> str:
    return f"{URL_BASE}/{identificador}"


def elegivel_automatico(status: str, score: float | None, *, score_minimo: float) -> bool:
    """Regra automática (§1 do complemento): só entra sozinho quem tem
    de-para OK e score de casamento >= o mínimo. Score ausente nunca passa
    automaticamente — mesmo com status OK, precisa de marcação humana
    (mesmo espírito do REVISAR: casamento sem confiança suficiente)."""
    return status == "OK" and score is not None and score >= score_minimo


# Brasil: DDI(2) + DDD(2) + número (8 ou 9 dígitos) = 12 ou 13 dígitos no
# total. Fora desse tamanho, mais vale marcar como "sem telefone" do que
# arriscar abrir o WhatsApp errado.
_TAMANHOS_VALIDOS_BR = (12, 13)


def normalizar_telefone(bruto: str | None, *, ddi: str = "55") -> str | None:
    """Telefone da Auvo vem em formatos variados ("(31) 9xxxx-xxxx",
    "31 9...", "5531..."). Tira tudo que não é dígito e prefixa o DDI se
    faltar. Devolve `None` se não sobrar um telefone plausível — melhor
    não mostrar o botão de WhatsApp do que abrir no contato errado."""
    if not bruto:
        return None
    digitos = re.sub(r"\D", "", bruto)
    if not digitos:
        return None
    if not digitos.startswith(ddi):
        digitos = ddi + digitos
    if ddi == "55" and len(digitos) not in _TAMANHOS_VALIDOS_BR:
        return None
    return digitos


def montar_link_whatsapp(telefone: str, mensagem: str) -> str:
    """`telefone` já deve vir normalizado (`normalizar_telefone`). Nunca
    dispara nada sozinho — só monta o link; quem confirma o envio é o
    humano que clica, dentro do próprio WhatsApp (§5.5 do complemento)."""
    return f"https://wa.me/{telefone}?text={quote(mensagem)}"


def formatar_telefone_exibicao(telefone: str) -> str:
    """Só para mostrar na tela — telefone normalizado (DDI+DDD+número)
    vira "(DD) 9NNNN-NNNN", sem o DDI. Formato não reconhecido volta como
    veio (nunca esconde o número por causa de formatação)."""
    digitos = telefone
    if digitos.startswith("55") and len(digitos) in _TAMANHOS_VALIDOS_BR:
        digitos = digitos[2:]
    if len(digitos) == 11:
        return f"({digitos[:2]}) {digitos[2:7]}-{digitos[7:]}"
    if len(digitos) == 10:
        return f"({digitos[:2]}) {digitos[2:6]}-{digitos[6:]}"
    return telefone
