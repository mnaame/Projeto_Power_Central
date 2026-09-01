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


def test_listar_todas_contas_pagina_e_usa_filtro_de_particao(requests_mock):
    from urllib.parse import parse_qs, urlparse

    _mock_login_ok(requests_mock)
    requests_mock.get(
        f"{CREDS.base_url}/Rest/Search/CuentaByDealer",
        [
            {"json": {"total": 3, "rows": [{"cue_ncuenta": "0095"}, {"cue_ncuenta": "0096"}]}},
            {"json": {"total": 3, "rows": [{"cue_ncuenta": "0097"}]}},
        ],
    )

    client = _client()
    contas = client.listar_todas_contas(page_size=2)

    assert [c["cue_ncuenta"] for c in contas] == ["0095", "0096", "0097"]
    query = parse_qs(urlparse(requests_mock.request_history[-1].url).query)
    assert '"cue_nparticion"' in query["filter"][0]
    assert '"sta_ncuentaenfallo"' not in query["filter"][0]  # não é o filtro de falha TST


def test_exportar_historico_html_monta_parametros_e_usa_token_do_cookie(requests_mock):
    from datetime import datetime
    from urllib.parse import parse_qs, urlparse

    _mock_login_ok(requests_mock)
    requests_mock.get(
        f"{CREDS.base_url}/handler/ExportReporteHistoricoExcel",
        content=b"<html><table><tr><td>Historico real</td></tr></table></html>",
    )

    client = _client()
    conteudo = client.exportar_historico_html(
        cue_iid="9385",
        numero_conta="0095",
        nome_cliente="CLINICA KENNEDY",
        desde=datetime(2026, 7, 1, 0, 0, 0),
        hasta=datetime(2026, 7, 31, 23, 59, 59),
        codigos_alarme=("CLO", "OPN", "BUR"),
    )

    assert b"Historico real" in conteudo
    query = parse_qs(urlparse(requests_mock.request_history[-1].url).query)
    assert query["token"] == ["abc123"]  # do cookie OAuth_Token do login
    assert query["FechaDesde"] == ["2026-07-01 00:00:00"]  # formato próprio do export
    assert query["FechaHasta"] == ["2026-07-31 23:59:59"]
    assert query["Codigoalarma"] == ["CLO,OPN,BUR"]
    assert query["dealerFirma"] == ["MIL"]
    assert query["CuentaReporte"] == ["9385"]
    assert query["CuentaNumero"] == ["0095"]
    assert query["cuentanombre"] == ["MIL - CLINICA KENNEDY"]
    assert query["exportToExcel"] == ["yes"]


def test_exportar_historico_html_recusado_por_permissao_levanta_erro(requests_mock):
    from datetime import datetime

    _mock_login_ok(requests_mock)
    requests_mock.get(
        f"{CREDS.base_url}/handler/ExportReporteHistoricoExcel",
        content="<html>no se encontró la página solicitada</html>".encode("utf-8"),
    )

    client = _client()
    with pytest.raises(SoftGuardError):
        client.exportar_historico_html(
            cue_iid="9385",
            numero_conta="0095",
            nome_cliente="CLINICA KENNEDY",
            desde=datetime(2026, 7, 1),
            hasta=datetime(2026, 7, 31),
            codigos_alarme=("CLO",),
        )


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


def test_listar_zonas_usa_o_filtro_da_tela(requests_mock):
    """Aceite §5: /Rest/Zona/ filtrado por zon_iidcuenta, com os dois
    filtros da própria tela (tira partições e zonas vazias)."""
    import json
    from urllib.parse import parse_qs, urlparse

    _mock_login_ok(requests_mock)
    requests_mock.get(
        f"{CREDS.base_url}/Rest/Zona/",
        json={
            "success": True,
            "total": 2,
            "rows": [
                {"zon_ccodigo": "1  ", "zon_cdescripcion": "MAG PORTA SALA", "zon_cAlarmaAGenerar": "NYR"},
                {"zon_ccodigo": "SP1", "zon_cdescripcion": "SENTINELLA: SOS", "zon_cAlarmaAGenerar": ""},
            ],
        },
    )

    zonas = _client().listar_zonas("9516")

    assert [z["zon_cdescripcion"] for z in zonas] == ["MAG PORTA SALA", "SENTINELLA: SOS"]

    query = parse_qs(urlparse(requests_mock.request_history[-1].url).query)
    filtro = json.loads(query["filter"][0])
    assert {"property": "zon_iidcuenta", "value": "9516"} in filtro
    assert {"property": "zon_ccodigo:LIKENOT", "value": "PAR"} in filtro
    assert {"property": "zon_ccodigo:ISNOTNULLOREMPTYTRIM", "value": ""} in filtro
    assert json.loads(query["sort"][0])[0]["property"] == "orderCodigo"
    assert query["limit"] == ["400"]
