import requests
import pytest

from app.integrations.softguard_client import (
    SoftGuardAuthError,
    SoftGuardClient,
    SoftGuardError,
    SoftGuardCredentials,
)

CREDS = SoftGuardCredentials(
    host="sistemas.example.com", port=8020, client_id="CID", username="user", password="pass"
)


def _mock_login_ok(requests_mock):
    requests_mock.get(f"{CREDS.base_url}/apps/Desktop/25.08.0/", text="ok")
    requests_mock.post(
        f"{CREDS.base_url}/OAuthLogin.ashx",
        headers={"Set-Cookie": "OAuth_Token=abc123; Path=/"},
        text="ok",
    )
    requests_mock.get(
        f"{CREDS.base_url}/rest/token/IsValid",
        json={"Message": "Ok", "Status": 1},
    )


def _client(**kwargs) -> SoftGuardClient:
    kwargs.setdefault("backoff_seconds", 0)
    kwargs.setdefault("max_retries", 2)
    return SoftGuardClient(CREDS, **kwargs)


def test_login_success(requests_mock):
    _mock_login_ok(requests_mock)

    client = _client()
    client.login()

    assert client.logged_in is True


def test_login_without_token_cookie_raises(requests_mock):
    requests_mock.get(f"{CREDS.base_url}/apps/Desktop/25.08.0/", text="ok")
    requests_mock.post(f"{CREDS.base_url}/OAuthLogin.ashx", text="ok")

    client = _client()
    with pytest.raises(SoftGuardAuthError):
        client.login()


def test_login_invalid_session_raises(requests_mock):
    requests_mock.get(f"{CREDS.base_url}/apps/Desktop/25.08.0/", text="ok")
    requests_mock.post(
        f"{CREDS.base_url}/OAuthLogin.ashx",
        headers={"Set-Cookie": "OAuth_Token=abc123; Path=/"},
        text="ok",
    )
    requests_mock.get(
        f"{CREDS.base_url}/rest/token/IsValid", json={"Message": "Fail", "Status": 0}
    )

    client = _client()
    with pytest.raises(SoftGuardAuthError):
        client.login()


def test_buscar_contas_pagina_ate_o_total(requests_mock):
    _mock_login_ok(requests_mock)

    pagina1 = {"total": 3, "data": [{"cue_ncuenta": "1"}, {"cue_ncuenta": "2"}]}
    pagina2 = {"total": 3, "data": [{"cue_ncuenta": "3"}]}

    requests_mock.get(
        f"{CREDS.base_url}/Rest/Search/CuentaByDealer",
        [{"json": pagina1}, {"json": pagina2}],
    )

    client = _client()
    contas = client.buscar_contas_em_falha_tst(page_size=2)

    assert [c["cue_ncuenta"] for c in contas] == ["1", "2", "3"]


def test_buscar_contas_faz_login_automatico_se_necessario(requests_mock):
    _mock_login_ok(requests_mock)
    requests_mock.get(
        f"{CREDS.base_url}/Rest/Search/CuentaByDealer",
        json={"total": 0, "data": []},
    )

    client = _client()
    assert client.logged_in is False

    contas = client.buscar_contas_em_falha_tst()

    assert contas == []
    assert client.logged_in is True


def test_falha_de_rede_apos_retries_gera_softguard_error(requests_mock):
    requests_mock.get(
        f"{CREDS.base_url}/apps/Desktop/25.08.0/", exc=requests.exceptions.ConnectTimeout
    )

    client = _client()
    with pytest.raises(SoftGuardError):
        client.login()


def test_resposta_nao_json_gera_softguard_error(requests_mock):
    requests_mock.get(f"{CREDS.base_url}/apps/Desktop/25.08.0/", text="ok")
    requests_mock.post(
        f"{CREDS.base_url}/OAuthLogin.ashx",
        headers={"Set-Cookie": "OAuth_Token=abc123; Path=/"},
        text="ok",
    )
    requests_mock.get(f"{CREDS.base_url}/rest/token/IsValid", text="<html>não é json</html>")

    client = _client()
    with pytest.raises(SoftGuardError):
        client.login()
