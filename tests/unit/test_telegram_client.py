import requests as requests_lib
import pytest

from app.integrations.telegram_client import (
    LIMITE_DOCUMENTO_BYTES,
    TIMEOUT_DOCUMENTO_SEGUNDOS,
    TelegramArquivoGrande,
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


UPDATES_URL = f"https://api.telegram.org/bot{CREDS.bot_token}/getUpdates"
DOCUMENT_URL = f"https://api.telegram.org/bot{CREDS.bot_token}/sendDocument"


def test_buscar_updates_manda_offset_e_timeout(requests_mock):
    from urllib.parse import parse_qs, urlparse

    requests_mock.get(
        UPDATES_URL, json={"ok": True, "result": [{"update_id": 7, "message": {"text": "/ajuda"}}]}
    )

    updates = TelegramClient(CREDS).buscar_updates(offset=5, timeout=25)

    assert [u["update_id"] for u in updates] == [7]
    query = parse_qs(urlparse(requests_mock.request_history[-1].url).query)
    assert query["offset"] == ["5"]
    assert query["timeout"] == ["25"]


def test_buscar_updates_sem_offset_omite_o_parametro(requests_mock):
    from urllib.parse import parse_qs, urlparse

    requests_mock.get(UPDATES_URL, json={"ok": True, "result": []})
    TelegramClient(CREDS).buscar_updates()
    assert "offset" not in parse_qs(urlparse(requests_mock.request_history[-1].url).query)


def test_buscar_updates_recusado_levanta(requests_mock):
    requests_mock.get(UPDATES_URL, json={"ok": False, "description": "unauthorized"})
    with pytest.raises(TelegramError):
        TelegramClient(CREDS).buscar_updates()


def test_enviar_documento(requests_mock):
    requests_mock.post(DOCUMENT_URL, json={"ok": True, "result": {"message_id": 9}})

    id_mensagem = TelegramClient(CREDS).enviar_documento(
        b"conteudo", nome_arquivo="0095_LOJA.xls", chat_id="-1", legenda="resumo"
    )

    assert id_mensagem == "9"
    assert "0095_LOJA.xls" in requests_mock.request_history[-1].text


def test_enviar_mensagem_para_chat_especifico(requests_mock):
    requests_mock.post(SEND_URL, json={"ok": True, "result": {"message_id": 1}})

    TelegramClient(CREDS).enviar_mensagem("oi", chat_id="-999")

    assert "chat_id=-999" in requests_mock.request_history[-1].text


def test_enviar_mensagem_sem_chat_usa_o_configurado(requests_mock):
    """Os alertas do coletor continuam indo para o chat configurado."""
    requests_mock.post(SEND_URL, json={"ok": True, "result": {"message_id": 1}})

    TelegramClient(CREDS).enviar_mensagem("oi")

    assert "chat_id=-100200300" in requests_mock.request_history[-1].text


# ---------- envio de arquivo grande ----------


def test_documento_usa_timeout_proprio_e_nao_o_das_mensagens(requests_mock):
    """Subir arquivo não é mandar uma linha de texto. Com os 10s das
    mensagens, o relatório de uma conta movimentada estourava no meio do
    upload: o técnico recebia o diagnóstico e o arquivo nunca chegava."""
    client = TelegramClient(CREDS, timeout=10)
    mock = requests_mock.post(
        f"https://api.telegram.org/bot{CREDS.bot_token}/sendDocument",
        json={"ok": True, "result": {"message_id": 7}},
    )

    client.enviar_documento(b"conteudo", nome_arquivo="r.xls")

    assert mock.last_request.timeout == TIMEOUT_DOCUMENTO_SEGUNDOS
    assert TIMEOUT_DOCUMENTO_SEGUNDOS > 10


def test_arquivo_acima_do_teto_e_recusado_antes_de_subir(requests_mock):
    """O Telegram recusa DEPOIS de receber o arquivo inteiro — checar
    antes evita gastar minutos de upload para ouvir não."""
    client = TelegramClient(CREDS)
    mock = requests_mock.post(f"https://api.telegram.org/bot{CREDS.bot_token}/sendDocument", json={"ok": True})

    with pytest.raises(TelegramArquivoGrande) as erro:
        client.enviar_documento(b"x" * (LIMITE_DOCUMENTO_BYTES + 1), nome_arquivo="r.xls")

    assert "MB" in str(erro.value)
    assert not mock.called  # nem tentou


def test_arquivo_no_limite_ainda_passa(requests_mock):
    client = TelegramClient(CREDS)
    requests_mock.post(
        f"https://api.telegram.org/bot{CREDS.bot_token}/sendDocument",
        json={"ok": True, "result": {"message_id": 7}},
    )

    assert client.enviar_documento(
        b"x" * LIMITE_DOCUMENTO_BYTES, nome_arquivo="r.xls"
    ) == "7"
