import pytest

from app.integrations.auvo_client import (
    AuvoClient,
    AuvoCredentials,
    AuvoError,
)

CREDS = AuvoCredentials(api_key="KEY", api_token="TOKEN", base_url="https://auvo.example/v2")


class RelogioFalso:
    def __init__(self, inicio=1000.0):
        self.agora = inicio

    def __call__(self):
        return self.agora

    def avancar(self, segundos):
        self.agora += segundos


def _mock_login(requests_mock, token="jwt-1"):
    return requests_mock.get(
        f"{CREDS.base_url}/login/", json={"result": {"accessToken": token}}
    )


def _client(clock=None):
    return AuvoClient(CREDS, clock=clock or RelogioFalso())


# ---------- login / token ----------


def test_login_extrai_token_de_result_accesstoken(requests_mock):
    mock = _mock_login(requests_mock)

    token = _client().login()

    assert token == "jwt-1"
    assert mock.last_request.qs["apikey"] == ["key"]  # querystring normalizada
    assert mock.last_request.qs["apitoken"] == ["token"]


@pytest.mark.parametrize(
    "resposta",
    [
        {"result": {"access_token": "jwt-alt"}},
        {"accessToken": "jwt-alt"},
        {"token": "jwt-alt"},
    ],
)
def test_login_aceita_formatos_alternativos_de_token(requests_mock, resposta):
    requests_mock.get(f"{CREDS.base_url}/login/", json=resposta)
    assert _client().login() == "jwt-alt"


def test_login_sem_token_na_resposta_levanta_erro(requests_mock):
    requests_mock.get(f"{CREDS.base_url}/login/", json={"result": {}})
    with pytest.raises(AuvoError):
        _client().login()


def test_login_resposta_nao_json_levanta_erro(requests_mock):
    requests_mock.get(f"{CREDS.base_url}/login/", text="<html>erro</html>", status_code=500)
    with pytest.raises(AuvoError):
        _client().login()


def test_token_renovado_apos_expirar(requests_mock):
    relogio = RelogioFalso()
    login = _mock_login(requests_mock)
    requests_mock.get(f"{CREDS.base_url}/customers/", json={"result": {"entityList": []}})

    client = _client(clock=relogio)
    client.listar_clientes()
    assert login.call_count == 1

    client.listar_clientes()  # token ainda válido — não reloga
    assert login.call_count == 1

    relogio.avancar(26 * 60)  # passou da margem de 25 min
    client.listar_clientes()
    assert login.call_count == 2


def test_401_refaz_login_e_repete_uma_vez(requests_mock):
    _mock_login(requests_mock)
    requests_mock.get(
        f"{CREDS.base_url}/customers/",
        [
            {"status_code": 401, "json": {}},
            {"status_code": 200, "json": {"result": {"entityList": [{"id": 1}]}}},
        ],
    )

    clientes = _client().listar_clientes()

    assert clientes == [{"id": 1}]


# ---------- listas paginadas ----------


def test_listar_clientes_pagina_ate_o_total(requests_mock):
    _mock_login(requests_mock)
    pagina1 = {
        "result": {
            "entityList": [{"id": i} for i in range(50)],
            "pagedSearchReturnData": {"totalItems": 60},
        }
    }
    pagina2 = {
        "result": {
            "entityList": [{"id": 50 + i} for i in range(10)],
            "pagedSearchReturnData": {"totalItems": 60},
        }
    }
    mock = requests_mock.get(
        f"{CREDS.base_url}/customers/", [{"json": pagina1}, {"json": pagina2}]
    )

    clientes = _client().listar_clientes()

    assert len(clientes) == 60
    assert mock.call_count == 2
    primeiro = mock.request_history[0]
    assert primeiro.qs["paramfilter"] == ["{}"]
    assert primeiro.qs["pagesize"] == ["50"]


def test_listar_para_na_pagina_incompleta_sem_total(requests_mock):
    _mock_login(requests_mock)
    requests_mock.get(
        f"{CREDS.base_url}/users/", json={"result": {"entityList": [{"id": 1}, {"id": 2}]}}
    )

    assert len(_client().listar_usuarios()) == 2


def test_listar_erro_http_levanta_auvo_error(requests_mock):
    _mock_login(requests_mock)
    requests_mock.get(f"{CREDS.base_url}/taskTypes/", status_code=500, json={"erro": "x"})

    with pytest.raises(AuvoError) as info:
        _client().listar_tipos_tarefa()
    assert info.value.status == 500


# ---------- criar tarefa ----------


def _payload_valido():
    return {
        "customerId": 13804973,
        "taskType": 145696,
        "orientation": "Título\nDescrição.",
        "priority": 2,
        "idUserFrom": 238031,
    }


def test_criar_tarefa_201_devolve_json(requests_mock):
    _mock_login(requests_mock)
    requests_mock.post(
        f"{CREDS.base_url}/tasks/",
        status_code=201,
        json={"result": {"taskID": 999}},
        headers={"Content-Type": "application/json"},
    )

    resposta = _client().criar_tarefa(_payload_valido())

    assert resposta == {"result": {"taskID": 999}}


def test_criar_tarefa_coage_ids_string_para_numero(requests_mock):
    # regra de ouro 3: customerId string dá 500 na Auvo — o client coage
    # ANTES de enviar (mesma proteção do motor validado)
    _mock_login(requests_mock)
    mock = requests_mock.post(
        f"{CREDS.base_url}/tasks/", status_code=201, json={},
        headers={"Content-Type": "application/json"},
    )

    payload = _payload_valido()
    payload["customerId"] = "13804973"
    payload["priority"] = "2"
    _client().criar_tarefa(payload)

    enviado = mock.last_request.json()
    assert enviado["customerId"] == 13804973
    assert isinstance(enviado["customerId"], int)
    assert enviado["priority"] == 2
    assert isinstance(enviado["priority"], int)


def test_criar_tarefa_campo_nao_numerico_falha_antes_do_http(requests_mock):
    _mock_login(requests_mock)
    mock = requests_mock.post(f"{CREDS.base_url}/tasks/", status_code=201, json={})

    payload = _payload_valido()
    payload["customerId"] = "abc"
    with pytest.raises(AuvoError):
        _client().criar_tarefa(payload)

    assert mock.call_count == 0  # nem chegou a chamar a API


def test_criar_tarefa_erro_carrega_corpo_e_resposta(requests_mock):
    # regra de ouro 8: em erro, corpo enviado + resposta ficam disponíveis
    # para o histórico (foi assim que cada campo foi descoberto)
    _mock_login(requests_mock)
    requests_mock.post(
        f"{CREDS.base_url}/tasks/",
        status_code=400,
        json={"errorCode": 124, "message": "User is not allowed to open task"},
    )

    with pytest.raises(AuvoError) as info:
        _client().criar_tarefa(_payload_valido())

    erro = info.value
    assert erro.status == 400
    assert erro.corpo_enviado["customerId"] == 13804973
    assert erro.resposta["errorCode"] == 124
