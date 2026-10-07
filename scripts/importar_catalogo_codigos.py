"""Gera o mapa descrição -> código a partir da planilha do catálogo.

Por que é necessário: o export da plataforma **não traz o código** do
evento, só a descrição (medido na conta 118 — 791 linhas, zero eventos
legíveis). O diagnóstico precisa do código, porque é nele que estão
escritas todas as regras, inclusive a de disparo, que é reconciliada
contra planilha manual e não vai ser reescrita para acomodar o export.

O mapa embutido no sistema tem só o punhado de descrições confirmadas em
export real. Este script lê o catálogo completo da plataforma e imprime o
conteúdo pronto para colar em **Configurações → `diag_descricoes`**.

Uso (PowerShell, na pasta do projeto — não precisa parar o serviço, não
acessa a plataforma):

  .venv\\Scripts\\python.exe scripts\\importar_catalogo_codigos.py catalogo_codigos_alarme.xlsx

Se as colunas não forem encontradas sozinhas, informe os títulos:

  ... catalogo_codigos_alarme.xlsx --codigo "Código" --descricao "Descrição"
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openpyxl import load_workbook  # noqa: E402

from app.domain import catalogo_eventos as dom_catalogo  # noqa: E402

# Títulos tentados em ordem, normalizados (a planilha varia de origem).
PISTAS_CODIGO = ("codigo", "code", "cod", "alarme", "sigla")
PISTAS_DESCRICAO = ("descricao", "description", "evento", "nome", "texto")


def _argumento(nome: str) -> str | None:
    if nome in sys.argv:
        indice = sys.argv.index(nome)
        if indice + 1 < len(sys.argv):
            return sys.argv[indice + 1]
    return None


def _achar_coluna(cabecalho, pistas, escolhido: str | None) -> int | None:
    titulos = [dom_catalogo.normalizar(str(c or "")) for c in cabecalho]
    if escolhido:
        alvo = dom_catalogo.normalizar(escolhido)
        for indice, titulo in enumerate(titulos):
            if titulo == alvo:
                return indice
        print(f"   !! coluna {escolhido!r} não existe. Títulos: {titulos}")
        return None
    for pista in pistas:
        for indice, titulo in enumerate(titulos):
            if titulo == pista:
                return indice
    for pista in pistas:
        for indice, titulo in enumerate(titulos):
            if pista in titulo:
                return indice
    return None


def main() -> None:
    caminhos = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not caminhos:
        print(__doc__)
        return
    caminho = caminhos[0]
    if not os.path.exists(caminho):
        print(f">>> Arquivo não encontrado: {caminho}")
        return

    planilha = load_workbook(caminho, read_only=True, data_only=True).active
    linhas = list(planilha.iter_rows(values_only=True))
    if not linhas:
        print(">>> Planilha vazia.")
        return

    cabecalho = linhas[0]
    print(f"1) CABEÇALHO: {[str(c) for c in cabecalho]}\n")
    col_codigo = _achar_coluna(cabecalho, PISTAS_CODIGO, _argumento("--codigo"))
    col_descricao = _achar_coluna(cabecalho, PISTAS_DESCRICAO, _argumento("--descricao"))
    print(f"2) COLUNAS: código -> {col_codigo}   descrição -> {col_descricao}")
    if col_codigo is None or col_descricao is None:
        print(
            "\n>>> Não achei as colunas sozinho. Rode de novo informando os\n"
            "    títulos exatos, como aparecem acima:\n"
            '    ... --codigo "Código" --descricao "Descrição"'
        )
        return

    pares: list[tuple[str, str]] = []
    ja_vistas: set[str] = set()
    repetidas = 0
    for linha in linhas[1:]:
        if col_codigo >= len(linha) or col_descricao >= len(linha):
            continue
        codigo = str(linha[col_codigo] or "").strip().upper()
        descricao = str(linha[col_descricao] or "").strip()
        if not codigo or not descricao:
            continue
        chave = dom_catalogo.normalizar(descricao)
        if chave in ja_vistas:
            # Duas descrições iguais com códigos diferentes: a primeira
            # vence, e o aviso no fim diz que houve ambiguidade.
            repetidas += 1
            continue
        ja_vistas.add(chave)
        pares.append((descricao, codigo))

    print(f"3) {len(pares)} par(es) lido(s).", end="")
    print(f" {repetidas} descrição(ões) repetida(s) ignorada(s)." if repetidas else "")

    faltando = [d for d in dom_catalogo.MAPA_PADRAO if d not in ja_vistas]
    if faltando:
        print(
            "\n   Atenção: estas descrições já confirmadas em export real NÃO\n"
            "   estão na planilha (o sistema continua reconhecendo, pelo mapa\n"
            "   padrão):"
        )
        for descricao in faltando:
            print(f"     - {descricao} = {dom_catalogo.MAPA_PADRAO[descricao]}")

    destino = os.path.splitext(caminho)[0] + "_diag_descricoes.txt"
    conteudo = "\n".join(f"{descricao}={codigo}" for descricao, codigo in pares)
    with open(destino, "w", encoding="utf-8") as arquivo:
        arquivo.write(conteudo)

    print(f"\n4) GRAVADO EM: {destino}")
    print(
        "\n>>> Abra esse arquivo, copie TUDO e cole em\n"
        "    Configurações -> diag_descricoes (só admin). Vale na hora,\n"
        "    sem reiniciar o serviço.\n\n"
        "    Depois confira numa conta conhecida:\n"
        "      .venv\\Scripts\\python.exe scripts\\debug_diagnostico.py 118 15"
    )


if __name__ == "__main__":
    main()
