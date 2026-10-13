"""Qual código o processo está rodando.

Existe porque "o pull foi feito" e "o processo carregou o código novo"
são coisas diferentes, e de fora elas são idênticas: a tela mostra o
comportamento antigo nos dois casos. Três rodadas de diagnóstico deste
sistema foram gastas atrás de bugs que já estavam corrigidos no disco.
"""

from datetime import timedelta

from app import build_info


def _repo(tmp_path, *, sha="347b388aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", ref="refs/heads/main"):
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text(f"ref: {ref}\n")
    (git / ref).write_text(sha + "\n")
    return git


def test_le_o_commit_e_o_branch_do_disco(tmp_path, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr(build_info, "RAIZ", tmp_path)

    info = build_info.info_build()

    assert info["commit"] == "347b388"
    assert info["branch"] == "main"


def test_commit_mais_novo_que_o_processo_e_sinalizado(tmp_path, monkeypatch):
    """O caso que motivou o módulo: `git pull` feito, `Restart-Service`
    esquecido."""
    git = _repo(tmp_path)
    monkeypatch.setattr(build_info, "RAIZ", tmp_path)
    monkeypatch.setattr(
        build_info, "INICIADO_EM", build_info.INICIADO_EM - timedelta(hours=2)
    )

    info = build_info.info_build()

    assert info["desatualizado"] is True
    assert info["atualizado_em"] > info["iniciado_em"]
    assert git.exists()


def test_processo_iniciado_depois_do_pull_esta_em_dia(tmp_path, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr(build_info, "RAIZ", tmp_path)
    monkeypatch.setattr(
        build_info, "INICIADO_EM", build_info.INICIADO_EM + timedelta(hours=2)
    )

    assert build_info.info_build()["desatualizado"] is False


def test_pull_e_restart_no_mesmo_minuto_nao_dao_alarme_falso(tmp_path, monkeypatch):
    """É o fluxo normal de deploy — o aviso não pode disparar nele, senão
    vira ruído e ninguém lê mais.

    A âncora é o mtime do ref, não `INICIADO_EM`: este módulo é importado
    no começo da suíte, então "20 s antes do import" pode ser minutos
    antes do arquivo ser escrito, e o teste passava sozinho e falhava na
    suíte inteira."""
    git = _repo(tmp_path)
    monkeypatch.setattr(build_info, "RAIZ", tmp_path)
    escrito_em = build_info._mtime(git / "refs" / "heads" / "main")
    monkeypatch.setattr(build_info, "INICIADO_EM", escrito_em - timedelta(seconds=20))

    assert build_info.info_build()["desatualizado"] is False


def test_sha_dentro_de_packed_refs(tmp_path, monkeypatch):
    """Depois de um `git gc` o ref não é mais um arquivo solto."""
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    (git / "packed-refs").write_text(
        "# pack-refs with: peeled fully-peeled sorted\n"
        "347b388aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa refs/heads/main\n"
        "999999aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa refs/heads/outro\n"
    )
    monkeypatch.setattr(build_info, "RAIZ", tmp_path)

    assert build_info.info_build()["commit"] == "347b388"


def test_sem_git_nao_derruba_a_pagina(tmp_path, monkeypatch):
    """Instalação a partir de um zip, sem repositório. O rodapé some, o
    sistema continua inteiro."""
    monkeypatch.setattr(build_info, "RAIZ", tmp_path)

    info = build_info.info_build()

    assert info["commit"] == ""
    assert info["desatualizado"] is False
