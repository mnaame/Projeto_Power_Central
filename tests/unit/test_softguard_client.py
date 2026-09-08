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


# ----------------------------------------------------------------------
# Token que vence no meio da operação
#
# Medido contra o portal em produção: a sessão morre em silêncio e o
# SoftGuard responde **500** (nunca 401) com "Invalid Token" no corpo. Uma
# consulta curta cabe na validade e passa; a paginação de um relatório de
# vários dias são centenas de requisições, leva minutos, e o token vence no
# meio — era essa a causa do 500 ao gerar relatórios longos.
# ----------------------------------------------------------------------

FALHA_TOKEN = (
    '<Fault xmlns="http://schemas.microsoft.com/ws/2005/05/envelope/none">'
    "<Reason><Text xml:lang=\"en-US\">Exception RaisedMessage: Exception has been "
    "thrown by the target of an invocation., InnerMessage: Invalid Token: FD"
    "</Text></Reason></Fault>"
)


def test_token_vencido_vira_erro_de_autenticacao_sem_repetir(requests_mock):
    """O 500 de token vencido não pode cair no laço de retentativa: repetir
    a mesma chamada com o mesmo token morto falha do mesmo jeito e só gasta
    o tempo do backoff."""
    _mock_login_ok(requests_mock)
    requests_mock.get(
        f"{CREDS.base_url}/Rest/search/EventoTimeLineFull",
        status_code=500,
        text=FALHA_TOKEN,
    )

    client = _client(max_retries=3)
    client.login()
    chamadas_antes = len(requests_mock.request_history)

    with pytest.raises(SoftGuardAuthError):
        client.buscar_timeline("123")

    # Uma tentativa + o login da renovação + a repetição — e não três
    # tentativas cegas por chamada.
    timeline = [
        r for r in requests_mock.request_history[chamadas_antes:]
        if "EventoTimeLineFull" in r.url
    ]
    assert len(timeline) == 2


def test_500_comum_continua_repetindo(requests_mock):
    """Só o token vencido é tratado como sessão morta. Um 500 qualquer
    continua sendo instabilidade do portal, com as retentativas de sempre."""
    _mock_login_ok(requests_mock)
    requests_mock.get(
        f"{CREDS.base_url}/Rest/search/EventoTimeLineFull",
        status_code=500,
        text="<Fault>banco fora do ar</Fault>",
    )

    client = _client(max_retries=2)
    client.login()
    chamadas_antes = len(requests_mock.request_history)

    with pytest.raises(SoftGuardError):
        client.buscar_timeline("123")

    timeline = [
        r for r in requests_mock.request_history[chamadas_antes:]
        if "EventoTimeLineFull" in r.url
    ]
    # Uma rodada de max_retries e para: sem token vencido não há por que
    # relogar, e relogar a cada 500 do portal só multiplicaria a carga.
    assert len(timeline) == 2


def test_login_comeca_com_cookie_jar_limpo(requests_mock):
    """Relogar por cima de um token morto é recusado pelo portal (medido:
    o mesmo login passa num `requests.Session` novo). Se o jar antigo
    sobrevivesse, a renovação automática falharia justamente na hora em que
    precisa funcionar."""
    _mock_login_ok(requests_mock)

    client = _client()
    client.login()
    client._session.cookies.set("OAuth_Token", "token-morto")
    client._session.cookies.set("lixo", "sobra-de-sessao-antiga")

    client.login()

    assert client._session.cookies.get("lixo") is None
    assert client._session.cookies.get("OAuth_Token") == "abc123"


def test_paginacao_renova_o_token_no_meio_e_termina_a_busca(requests_mock):
    """O caso real do relatório de vários dias: as primeiras páginas vêm, o
    token vence, e a busca precisa continuar de onde parou — não recomeçar
    nem morrer."""
    _mock_login_ok(requests_mock)
    requests_mock.get(
        f"{CREDS.base_url}/Rest/Search/CuentaByDealer",
        [
            {"json": {"total": 4, "rows": [{"cue_ncuenta": "1"}, {"cue_ncuenta": "2"}]}},
            {"status_code": 500, "text": FALHA_TOKEN},
            {"json": {"total": 4, "rows": [{"cue_ncuenta": "3"}, {"cue_ncuenta": "4"}]}},
        ],
    )

    client = _client()
    contas = client.buscar_contas_em_falha_tst(page_size=2)

    assert [c["cue_ncuenta"] for c in contas] == ["1", "2", "3", "4"]
    # Relogou de verdade no meio do caminho (o login aparece duas vezes).
    logins = [r for r in requests_mock.request_history if "OAuthLogin" in r.url]
    assert len(logins) == 2
