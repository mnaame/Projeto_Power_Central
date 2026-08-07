"""Links da Central do Cliente (Auvo) — lógica pura (sem I/O). O cliente
HTTP fica em `integrations/auvo_painel_client.py`; a orquestração
(elegibilidade real contra o banco, criação, auditoria) fica em
`services/central_cliente_service.py`.
"""

from __future__ import annotations

import secrets

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
