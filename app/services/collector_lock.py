from __future__ import annotations

import threading

_lock = threading.Lock()


def tentar_adquirir() -> bool:
    """Exclusão mútua entre o ciclo agendado e o botão manual (RF1/RF4) —
    lock em memória, único processo (ver docs/ARQUITETURA.md seção 1.2)."""
    return _lock.acquire(blocking=False)


def liberar() -> None:
    try:
        _lock.release()
    except RuntimeError:
        pass


def em_execucao() -> bool:
    if _lock.acquire(blocking=False):
        _lock.release()
        return False
    return True
