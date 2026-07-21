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
    # Formato real da API (validado em produção): envelope success/total/rows.
    _mock_login_ok(requests_mock)

    pagina1 = {"success": True, "total": 3, "rows": [{"cue_ncuenta": "1"}, {"cue_ncuenta": "2"}]}
    pagina2 = {"success": True, "total": 3, "rows": [{"cue_ncuenta": "3"}]}

    requests_mock.get(
        f"{CREDS.base_url}/Rest/Search/CuentaByDealer",
        [{"json": pagina1}, {"json": pagina2}],
    )

    client = _client()
    contas = client.buscar_contas_em_falha_tst(page_size=2)

    assert [c["cue_ncuenta"] for c in contas] == ["1", "2", "3"]


def test_buscar_contas_aceita_fallback_data(requests_mock):
    _mock_login_ok(requests_mock)
    requests_mock.get(
        f"{CREDS.base_url}/Rest/Search/CuentaByDealer",
        json={"total": 1, "data": [{"cue_ncuenta": "7"}]},
    )

    client = _client()
    contas = client.buscar_contas_em_falha_tst()

    assert [c["cue_ncuenta"] for c in contas] == ["7"]


def test_buscar_contas_faz_login_automatico_se_necessario(requests_mock):
    _mock_login_ok(requests_mock)
    requests_mock.get(
        f"{CREDS.base_url}/Rest/Search/CuentaByDealer",
        json={"success": True, "total": 0, "rows": []},
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


def test_buscar_historico_monta_parametros_e_pagina(requests_mock):
    from datetime import datetime
    from urllib.parse import parse_qs, urlparse

    _mock_login_ok(requests_mock)
    requests_mock.get(
        f"{CREDS.base_url}/Rest/Search/ReporteHistorico",
        [
            {"json": {"success": True, "total": 3, "rows": [{"rec_iid": "1"}, {"rec_iid": "2"}]}},
            {"json": {"success": True, "total": 3, "rows": [{"rec_iid": "3"}]}},
        ],
    )

    client = _client()
    eventos = client.buscar_historico(
        codigos_alarme=("NYE", "NYC"),
        desde=datetime(2026, 7, 18, 0, 0, 0),
        hasta=datetime(2026, 7, 18, 23, 59, 59),
        page_size=2,
    )

    assert [e["rec_iid"] for e in eventos] == ["1", "2", "3"]

    query = parse_qs(urlparse(requests_mock.request_history[-1].url).query)
    assert query["FechaDesde"] == ["07-18-2026 00:00:00"]
    assert query["FechaHasta"] == ["07-18-2026 23:59:59"]
    assert query["CodigosAlarma"] == ["NYE,NYC"]
    assert query["table"] == ["p_recepcion"]
    assert query["OrdenarFecha"] == ["DESC"]
    assert query["Mostrar"] == ["5000"]


def test_buscar_timeline_retorna_passos(requests_mock):
    from urllib.parse import parse_qs, urlparse

    _mock_login_ok(requests_mock)
    requests_mock.get(
        f"{CREDS.base_url}/Rest/search/EventoTimeLineFull",
        json={"success": True, "total": 2, "rows": [{"etl_cAccion": "Inicio"}, {"etl_cAccion": "Procesar"}]},
    )

    client = _client()
    passos = client.buscar_timeline("9385")

    assert [p["etl_cAccion"] for p in passos] == ["Inicio", "Procesar"]

    query = parse_qs(urlparse(requests_mock.request_history[-1].url).query)
    assert query["IdEvento"] == ["9385"]
    assert query["limit"] == ["500"]
