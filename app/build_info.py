"""Qual código este processo está rodando — e se ele já está velho.

Existe por um motivo caro: **três rodadas de diagnóstico deste sistema
foram gastas investigando bugs que já estavam corrigidos no disco**. O
`git pull` troca os arquivos, mas o processo do Flask continua com o
módulo que carregou no `import`; sem `Restart-Service`, a correção está
no repositório e não no ar. De fora as duas situações são idênticas — a
tela mostra o comportamento antigo, e o próximo passo lógico (errado) é
procurar outro bug.

Daí a comparação que importa aqui: **o commit no disco é mais novo que o
processo?** Se for, o que está na tela não é o que está no código, e o
rodapé diz isso em vez de deixar a pessoa adivinhar.

Lê o `.git` direto, sem chamar o `git`: o serviço roda como uma conta de
sistema que pode não ter o executável no PATH, e um subprocesso por
request seria caro à toa. Tudo aqui é defensivo — nenhuma falha de
leitura pode derrubar uma página: sem `.git`, a resposta é "desconhecida"
e a vida segue.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

# Hora em que ESTE processo importou o módulo, ou seja, quando o serviço
# subiu. É o lado "processo" da comparação.
INICIADO_EM = datetime.now(timezone.utc)

RAIZ = Path(__file__).resolve().parent.parent


def _ler(caminho: Path) -> str:
    try:
        return caminho.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _sha_do_ref(git: Path, ref: str) -> str:
    """O SHA pode estar num arquivo solto ou dentro de `packed-refs` —
    depende de o repositório ter passado por um `git gc`."""
    solto = _ler(git / ref)
    if solto:
        return solto
    for linha in _ler(git / "packed-refs").splitlines():
        if linha.startswith("#") or " " not in linha:
            continue
        sha, nome = linha.split(" ", 1)
        if nome.strip() == ref:
            return sha.strip()
    return ""


def _mtime(caminho: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(caminho.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def info_build() -> dict:
    """`{"commit", "branch", "atualizado_em", "iniciado_em", "desatualizado"}`.

    `atualizado_em` é o mtime do ref do branch: é o instante em que o
    `git pull` escreveu o commit novo no disco. Comparado com
    `iniciado_em`, responde a única pergunta que interessa depois de um
    deploy — este processo carregou este código?"""
    git = RAIZ / ".git"
    cabeca = _ler(git / "HEAD")

    branch, ref = "", ""
    if cabeca.startswith("ref:"):
        ref = cabeca.split(" ", 1)[1].strip()
        branch = ref.rsplit("/", 1)[-1]
        sha = _sha_do_ref(git, ref)
        atualizado_em = _mtime(git / ref) or _mtime(git / "packed-refs")
    else:  # HEAD solto (checkout de commit) — raro aqui, mas não quebra
        sha = cabeca
        atualizado_em = _mtime(git / "HEAD")

    return {
        "commit": sha[:7] if sha else "",
        "branch": branch,
        "atualizado_em": atualizado_em,
        "iniciado_em": INICIADO_EM,
        # A margem de 1 min evita alarme falso quando o pull e o restart
        # acontecem no mesmo minuto, que é o fluxo normal de deploy.
        "desatualizado": bool(
            atualizado_em and (atualizado_em - INICIADO_EM).total_seconds() > 60
        ),
    }
