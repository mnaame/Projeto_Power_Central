import requests as requests_lib
import pytest

from app.integrations.telegram_client import (
    TelegramClient,
    TelegramCredentials,
    TelegramError,
    dividir_mensagem,
)

CREDS = TelegramCredentials(bot_token="TOKEN", chat_id="-100200300")
SEND_URL = f"https://api.telegram.org/bot{CREDS.bot_token}/sendMessage"


def test_enviar_mensagem_curta(requests_mock):
    requests_mock.post(SEND_URL, json={"ok": True, "result": {"message_id": 42}})

    client = TelegramClient(CREDS)
    ids = client.enviar_mensagem("<b>Teste</b>")

    assert ids == ["42"]


def test_enviar_mensagem_longa_divide_em_partes(requests_mock):
    requests_mock.post(
        SEND_URL,
        [
            {"json": {"ok": True, "result": {"message_id": 1}}},
            {"json": {"ok": True, "result": {"message_id": 2}}},
        ],
    )
    texto = "\n\n".join(f"linha {i} " + "x" * 100 for i in range(60))  # > 4096 chars

    client = TelegramClient(CREDS)
    ids = client.enviar_mensagem(texto)

    assert ids == ["1", "2"]


def test_telegram_recusa_mensagem_gera_erro(requests_mock):
    requests_mock.post(SEND_URL, json={"ok": False, "description": "chat not found"})

    client = TelegramClient(CREDS)
    with pytest.raises(TelegramError):
        client.enviar_mensagem("oi")


def test_falha_de_rede_gera_telegram_error(requests_mock):
    requests_mock.post(SEND_URL, exc=requests_lib.exceptions.ConnectTimeout)

    client = TelegramClient(CREDS)
    with pytest.raises(TelegramError):
        client.enviar_mensagem("oi")


def test_dividir_mensagem_texto_curto():
    assert dividir_mensagem("abc") == ["abc"]


def test_dividir_mensagem_corta_na_quebra_de_linha():
    linha = "x" * 100
    texto = "\n\n".join([linha] * 60)

    partes = dividir_mensagem(texto, limite=500)

    assert len(partes) > 1
    assert all(len(p) <= 500 for p in partes)
    assert all(p for p in partes)


def test_dividir_mensagem_corta_mesmo_sem_quebra_de_linha():
    texto = "y" * 5000

    partes = dividir_mensagem(texto, limite=2000)

    assert all(len(p) <= 2000 for p in partes)
    assert sum(len(p) for p in partes) == 5000
