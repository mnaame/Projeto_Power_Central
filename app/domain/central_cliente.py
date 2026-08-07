"""Links da Central do Cliente (Auvo) — lógica pura (sem I/O). O cliente
HTTP fica em `integrations/auvo_painel_client.py`; a orquestração
(elegibilidade real contra o banco, criação, auditoria) fica em
`services/central_cliente_service.py`.
"""

from __future__ import annotations

import uuid

# ATENÇÃO — NÃO CONFIRMADO (ver docs/CENTRAL_CLIENTE.md §6, item 1): o
# complemento original suspeita que a Auvo gera o identificador no formato
# 8-4-4-4-13 (hex), não o UUID v4 padrão (8-4-4-4-12). Até confirmar contra
# um link real capturado no F12, usamos o UUID padrão. Função isolada de
# propósito: se o formato certo for outro, o ajuste é só aqui.
def gerar_identificador() -> str:
    return str(uuid.uuid4())


URL_BASE = "https://novomillenium.auvo.com.br/share"


def montar_url(identificador: str) -> str:
    return f"{URL_BASE}/{identificador}"


def elegivel_automatico(status: str, score: float | None, *, score_minimo: float) -> bool:
    """Regra automática (§1 do complemento): só entra sozinho quem tem
    de-para OK e score de casamento >= o mínimo. Score ausente nunca passa
    automaticamente — mesmo com status OK, precisa de marcação humana
    (mesmo espírito do REVISAR: casamento sem confiança suficiente)."""
    return status == "OK" and score is not None and score >= score_minimo
