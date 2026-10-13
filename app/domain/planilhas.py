"""Lê as planilhas que a Auvo e a PowerCentral exportam.

Camada pura: recebe bytes, devolve linhas. Nada de banco, nada de rede.

São dois formatos bem diferentes, e nenhum dos dois é escolha nossa:

- **Auvo**: `.xlsx` de verdade, com uma linha de cabeçalho e uma segunda
  linha de ajuda que não é dado.
- **PowerCentral**: arquivo `.xls` que **não é Excel** — é uma tabela
  HTML com o nome trocado. Abrir com uma biblioteca de xls falha; o que
  funciona é lê-lo como HTML mesmo.

**As colunas são achadas pelo nome do cabeçalho, nunca pela posição.**
Posição muda quando alguém marca uma coluna a mais na tela de exportação,
e o estrago seria silencioso: o sistema leria "telefone" como "bairro" e
seguiria em frente. Pelo nome, uma coluna que mudou de lugar continua
sendo achada, e uma que sumiu vira erro explícito.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser

from app.domain.endereco import normalizar


class PlanilhaInvalida(Exception):
    """O arquivo não é a planilha esperada (ou está sem as colunas)."""


@dataclass(frozen=True)
class LinhaPlanilha:
    """Uma linha já identificada, antes de virar endereço."""

    conta: str = ""
    id_auvo: int | None = None
    nome: str = ""
    endereco: str = ""
    cidade: str = ""


# ----------------------------------------------------------------------
# Leitura bruta de cada formato
# ----------------------------------------------------------------------


class _TabelaHTML(HTMLParser):
    """O .xls da PowerCentral é uma tabela HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.linhas: list[list[str]] = []
        self._linha: list[str] | None = None
        self._celula: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._linha = []
        elif tag in ("td", "th"):
            self._celula = []

    def handle_endtag(self, tag):
        if tag == "tr" and self._linha is not None:
            if any(c.strip() for c in self._linha):
                self.linhas.append(self._linha)
            self._linha = None
        elif tag in ("td", "th") and self._linha is not None:
            self._linha.append(" ".join("".join(self._celula or []).split()))
            self._celula = None

    def handle_data(self, data):
        if self._celula is not None:
            self._celula.append(data)


def ler_html(conteudo: bytes) -> list[list[str]]:
    # O portal exporta em latin-1; `errors="replace"` porque um acento
    # estranho numa linha não pode impedir a leitura das outras 147.
    texto = conteudo.decode("latin-1", errors="replace")
    parser = _TabelaHTML()
    parser.feed(texto)
    return parser.linhas


_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def ler_xlsx(conteudo: bytes) -> list[list[str]]:
    """Lê o xlsx direto do zip.

    Sem openpyxl de propósito: o arquivo vem de fora, e o caminho mais
    curto entre bytes de terceiro e um objeto complexo é o que costuma
    surpreender. Aqui são duas partes do zip e um parse de XML."""
    from xml.etree import ElementTree

    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
            nomes = z.namelist()
            compartilhadas: list[str] = []
            if "xl/sharedStrings.xml" in nomes:
                raiz = ElementTree.fromstring(z.read("xl/sharedStrings.xml"))
                compartilhadas = [
                    "".join(t.text or "" for t in si.iter(f"{_NS}t"))
                    for si in raiz.findall(f"{_NS}si")
                ]
            planilha = next(
                (n for n in nomes if n.startswith("xl/worksheets/sheet")), ""
            )
            if not planilha:
                raise PlanilhaInvalida("O arquivo .xlsx não tem nenhuma aba.")
            raiz = ElementTree.fromstring(z.read(planilha))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise PlanilhaInvalida(f"Não consegui ler o arquivo .xlsx: {exc}") from exc

    linhas: list[list[str]] = []
    for row in raiz.iter(f"{_NS}row"):
        celulas: dict[int, str] = {}
        for c in row.findall(f"{_NS}c"):
            indice = _coluna_para_indice(c.get("r") or "")
            tipo = c.get("t")
            if tipo == "inlineStr":
                # Texto gravado dentro da própria célula. A Auvo usa a
                # tabela de strings compartilhadas, mas outros
                # exportadores escrevem assim — e um xlsx que o Excel abre
                # não pode falhar aqui.
                texto = "".join(t.text or "" for t in c.iter(f"{_NS}t"))
            else:
                v = c.find(f"{_NS}v")
                texto = v.text if v is not None else ""
                if tipo == "s" and texto is not None:
                    try:
                        texto = compartilhadas[int(texto)]
                    except (ValueError, IndexError):
                        texto = ""
            celulas[indice] = texto or ""
        if celulas:
            linhas.append([celulas.get(i, "") for i in range(max(celulas) + 1)])
    return linhas


def _coluna_para_indice(referencia: str) -> int:
    """"B7" -> 1. O xlsx omite célula vazia, então sem isto as colunas
    saem deslocadas justamente nas linhas com campo em branco."""
    indice = 0
    for caractere in referencia:
        if not caractere.isalpha():
            break
        indice = indice * 26 + (ord(caractere.upper()) - 64)
    return indice - 1


# ----------------------------------------------------------------------
# Identificação das colunas (por nome, nunca por posição)
# ----------------------------------------------------------------------


def achar_coluna(cabecalho: list[str], *candidatos: str) -> int | None:
    """Índice da primeira coluna cujo título bate. Compara normalizado:
    "Localização da conta" e "LOCALIZACAO DA CONTA" são a mesma coluna."""
    titulos = [normalizar(c) for c in cabecalho]
    for candidato in candidatos:
        alvo = normalizar(candidato)
        for indice, titulo in enumerate(titulos):
            if titulo == alvo:
                return indice
    return None


def _celula(linha: list[str], indice: int | None) -> str:
    if indice is None or indice >= len(linha):
        return ""
    return str(linha[indice] or "").strip()


def ler_planilha_auvo(conteudo: bytes) -> list[LinhaPlanilha]:
    """Export de clientes da Auvo (`Código`, `Nome`, `Endereço`).

    A segunda linha do arquivo é instrução de preenchimento da própria
    Auvo ("Nome do cliente que será cadastrado...", "Endereço do cliente.
    Com informações completas..."), não é cliente. O que a separa é o
    `Código`: todo cliente de verdade tem um, a linha de ajuda não — por
    isso o código é exigido aqui, e não só o nome."""
    linhas = ler_xlsx(conteudo)
    if not linhas:
        raise PlanilhaInvalida("A planilha da Auvo está vazia.")

    cabecalho = linhas[0]
    i_nome = achar_coluna(cabecalho, "Nome", "Cliente", "Descrição")
    i_end = achar_coluna(cabecalho, "Endereço", "Endereco", "Address")
    i_cod = achar_coluna(cabecalho, "Código", "Codigo", "Id")
    if i_nome is None or i_end is None:
        raise PlanilhaInvalida(
            "Não achei as colunas 'Nome' e 'Endereço'. "
            "Exporte os clientes pela Auvo sem renomear as colunas."
        )

    registros = []
    for linha in linhas[1:]:
        nome = _celula(linha, i_nome)
        if not nome:
            continue
        bruto_id = _celula(linha, i_cod)
        try:
            id_auvo = int(float(bruto_id)) if bruto_id else None
        except ValueError:
            id_auvo = None
        if id_auvo is None:
            continue
        registros.append(
            LinhaPlanilha(id_auvo=id_auvo, nome=nome, endereco=_celula(linha, i_end))
        )
    return registros


def ler_planilha_power(conteudo: bytes) -> list[LinhaPlanilha]:
    """Relatório de contas da PowerCentral (`Dealer / Conta`, `Nome`,
    `Localidade`).

    Daqui sai a **cidade**, não o bairro: das 148 contas do relatório
    real, a coluna "Rua" tinha bairro legível em uma. A cidade, por outro
    lado, vem preenchida em praticamente todas — e é ela que coloca num
    mapa mental o cliente que não casou com a Auvo."""
    linhas = ler_html(conteudo)
    if not linhas:
        raise PlanilhaInvalida(
            "Não achei nenhuma tabela no arquivo. O relatório da "
            "PowerCentral é um .xls que por dentro é HTML — envie o "
            "arquivo como ele é baixado, sem reabrir e salvar pelo Excel."
        )

    cabecalho = linhas[0]
    i_conta = achar_coluna(cabecalho, "Dealer / Conta", "Conta", "Dealer/Conta")
    i_nome = achar_coluna(cabecalho, "Nome", "Cliente")
    i_cidade = achar_coluna(cabecalho, "Localidade", "Cidade")
    i_rua = achar_coluna(cabecalho, "Rua", "Endereço", "Endereco")
    if i_conta is None or i_nome is None:
        raise PlanilhaInvalida(
            "Não achei as colunas 'Dealer / Conta' e 'Nome' no relatório."
        )

    registros = []
    for linha in linhas[1:]:
        nome = _celula(linha, i_nome)
        bruto = _celula(linha, i_conta)
        if not nome or not bruto:
            continue
        # "MIL-0001" -> "0001"; o número é o que o resto do sistema usa.
        conta = bruto.split("-")[-1].strip()
        registros.append(
            LinhaPlanilha(
                conta=conta,
                nome=nome,
                cidade=_celula(linha, i_cidade),
                endereco=_celula(linha, i_rua),
            )
        )
    return registros


def detectar(conteudo: bytes) -> str:
    """"auvo" ou "power" pelo conteúdo do arquivo, não pela extensão.

    O relatório da PowerCentral se chama `.xls` e é HTML; pedir para a
    pessoa acertar qual é qual seria transferir para ela um problema que
    os dois primeiros bytes resolvem."""
    if conteudo[:2] == b"PK":
        return "auvo"
    return "power"
