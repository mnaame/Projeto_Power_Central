import json

import pytest

from app.domain import cofre_backup as dom


SENHA_BOA = "frase-longa-de-backup-2026"


def test_ida_e_volta_preserva_os_itens():
    itens = [
        {"titulo": "DVR Loja", "senha": "s3nh4-dvr", "notas": "porta 8080"},
        {"titulo": "Roteador", "senha": "outra-senha", "notas": ""},
    ]

    pacote = dom.empacotar(itens, senha=SENHA_BOA, iteracoes=1000)

    assert dom.desempacotar(pacote, senha=SENHA_BOA) == itens


def test_senha_errada_nao_abre():
    pacote = dom.empacotar([{"titulo": "x", "senha": "y"}], senha=SENHA_BOA, iteracoes=1000)

    with pytest.raises(dom.BackupSenhaInvalidaError):
        dom.desempacotar(pacote, senha="outra-frase-de-backup")


def test_arquivo_adulterado_nao_abre():
    """Fernet é autenticado: mexer no conteúdo invalida, não devolve lixo."""
    pacote = dom.empacotar([{"titulo": "x", "senha": "y"}], senha=SENHA_BOA, iteracoes=1000)
    envelope = json.loads(pacote)
    envelope["conteudo"] = envelope["conteudo"][:-8] + "AAAAAAAA"

    with pytest.raises(dom.BackupSenhaInvalidaError):
        dom.desempacotar(json.dumps(envelope).encode(), senha=SENHA_BOA)


def test_nenhuma_senha_aparece_em_claro_no_arquivo():
    """O teste que mais importa: o arquivo não pode ser um vazamento."""
    pacote = dom.empacotar(
        [{"titulo": "DVR", "senha": "SENHA-SUPER-SECRETA", "notas": "NOTA-SECRETA"}],
        senha=SENHA_BOA,
        iteracoes=1000,
    )

    texto = pacote.decode()
    assert "SENHA-SUPER-SECRETA" not in texto
    assert "NOTA-SECRETA" not in texto
    assert "DVR" not in texto  # nem o título escapa
    assert SENHA_BOA not in texto  # nem a senha do próprio backup


def test_metadados_ficam_legiveis_sem_a_senha():
    """Dá para conferir data e quantidade sem abrir o cofre — é o que
    permite escolher entre dois arquivos antes de tentar restaurar."""
    pacote = dom.empacotar(
        [{"titulo": "a", "senha": "1"}, {"titulo": "b", "senha": "2"}],
        senha=SENHA_BOA,
        iteracoes=1000,
    )

    meta = dom.ler_metadados(pacote)

    assert meta["itens"] == 2
    assert meta["formato"] == dom.FORMATO
    assert meta["criado_em"]


def test_dois_backups_da_mesma_senha_usam_sais_diferentes():
    a = json.loads(dom.empacotar([], senha=SENHA_BOA, iteracoes=1000))
    b = json.loads(dom.empacotar([], senha=SENHA_BOA, iteracoes=1000))

    assert a["kdf"]["salt"] != b["kdf"]["salt"]
    assert a["conteudo"] != b["conteudo"]


def test_senha_curta_e_recusada_na_geracao():
    with pytest.raises(dom.BackupSenhaFracaError):
        dom.empacotar([{"titulo": "x", "senha": "y"}], senha="curta")


def test_arquivo_que_nao_e_backup_da_erro_de_formato():
    with pytest.raises(dom.BackupFormatoInvalidoError):
        dom.ler_metadados(b"isto nao e json")

    with pytest.raises(dom.BackupFormatoInvalidoError):
        dom.ler_metadados(json.dumps({"formato": "outra-coisa"}).encode())


def test_versao_desconhecida_e_recusada():
    envelope = json.loads(dom.empacotar([], senha=SENHA_BOA, iteracoes=1000))
    envelope["versao"] = 99

    with pytest.raises(dom.BackupFormatoInvalidoError):
        dom.ler_metadados(json.dumps(envelope).encode())


def test_envelope_sem_kdf_e_recusado_sem_estourar():
    envelope = json.loads(dom.empacotar([], senha=SENHA_BOA, iteracoes=1000))
    del envelope["kdf"]

    with pytest.raises(dom.BackupFormatoInvalidoError):
        dom.desempacotar(json.dumps(envelope).encode(), senha=SENHA_BOA)


def test_a_chave_derivada_depende_do_sal():
    assert dom.derivar_chave("mesma-senha", b"sal-um-aaaaaaaa", iteracoes=1000) != (
        dom.derivar_chave("mesma-senha", b"sal-dois-bbbbbb", iteracoes=1000)
    )
