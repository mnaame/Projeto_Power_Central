"""Relatório do Técnico do Dia — envelopa o motor validado do
`relatorio_tecnico.py`: match de técnico na tarefa da Auvo, nome de
arquivo por loja, e a conversão do HTML nativo da plataforma (o export
"Excel" real é HTML) para um `.xlsx` de verdade preservando as cores por
tipo de evento.

Fica em `domain/` por ser lógica pura (sem rede) — a única parte "impura"
é a montagem do Workbook em memória; salvar em disco é responsabilidade
de quem chama (`services/tecnico_service.py`).
"""

from __future__ import annotations

import html as _html
import re
import unicodedata
from typing import Mapping, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# Campos tentados em ordem — o primeiro não-vazio identifica o técnico da
# tarefa (nomes variam conforme a versão da API da Auvo).
_CAMPOS_TECNICO = ("userToName", "idUserToName", "userTo", "responsavel", "idUserTo")

_MARCADOR_ERRO_1 = "no se encontr"
_MARCADOR_ERRO_2 = "regularizar la situaci"

_LARGURA_COLUNA_PADRAO = 22
COR_CABECALHO = "21A366"
_TEXTO_CABECALHO = "data e hora do evento"

TAM_MAX_NOME_ARQUIVO = 40


def _texto(valor: object) -> str:
    return str(valor).strip() if valor is not None else ""


def _sem_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


def nome_tecnico_da_tarefa(tarefa: Mapping[str, object]) -> str:
    """Primeiro campo não-vazio entre os candidatos conhecidos."""
    for campo in _CAMPOS_TECNICO:
        valor = _texto(tarefa.get(campo))
        if valor:
            return valor
    return ""


def tecnico_corresponde(tarefa: Mapping[str, object], alvo: str) -> bool:
    """Substring, sem acento, case-insensitive. Alvo vazio = "todos"."""
    alvo = _texto(alvo)
    if not alvo:
        return True
    nome = _sem_acentos(nome_tecnico_da_tarefa(tarefa)).lower()
    return _sem_acentos(alvo).lower() in nome


def sanitizar_nome_arquivo(nome: str, *, tamanho_maximo: int = TAM_MAX_NOME_ARQUIVO) -> str:
    """Só alfanumérico, espaço, hífen e underline — trunca. Mesma regra
    do motor validado, para os nomes dos arquivos baterem com o que a
    operação já está acostumada a ver."""
    limpo = "".join(c if c.isalnum() or c in " -_" else "_" for c in (nome or ""))
    return limpo[:tamanho_maximo].strip()


def nome_arquivo_loja(numero_conta: str, nome_cliente: str, *, extensao: str = "xls") -> str:
    """`<conta 4 dígitos>_<nome sanitizado>.<extensao>` — mesmo padrão do
    motor validado (CuentaNumero também é enviado com 4 dígitos)."""
    numero = (numero_conta or "0").zfill(4)
    return f"{numero}_{sanitizar_nome_arquivo(nome_cliente)}.{extensao}"


def exportacao_recusada(conteudo: bytes) -> bool:
    """True quando o HTML devolvido é a página de erro de permissão da
    PowerCentral, não o histórico de verdade."""
    texto = conteudo.decode("utf-8", "replace").lower()
    return _MARCADOR_ERRO_1 in texto or _MARCADOR_ERRO_2 in texto


def _cor_do_estilo(estilo: str, propriedade: str) -> str | None:
    encontrado = re.search(propriedade + r"\s*:\s*#([0-9a-fA-F]{6})", estilo or "")
    return encontrado.group(1).upper() if encontrado else None


def montar_workbook_colorido(html: str) -> Workbook:
    """Converte o HTML nativo do export num `.xlsx` de verdade,
    preservando as cores de fundo/texto de cada evento (mesma lógica do
    motor validado). Devolve o Workbook em memória — salvar é por conta
    de quem chama."""
    workbook = Workbook()
    planilha = workbook.active
    planilha.title = "Historico"
    cabecalho_marcado = False
    linha_atual = 1

    for linha_html in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        celulas = re.findall(r"<t[dh]([^>]*)>(.*?)</t[dh]>", linha_html, re.S | re.I)
        dados: list[tuple[str, str | None, str | None]] = []
        for atributos, conteudo_cel in celulas:
            texto = re.sub(r"<[^>]+>", "", conteudo_cel)
            texto = _html.unescape(texto).replace("\xa0", " ").strip()
            estilo_bruto = re.search(r'style\s*=\s*"([^"]*)"', atributos)
            estilo = estilo_bruto.group(1) if estilo_bruto else ""
            dados.append(
                (texto, _cor_do_estilo(estilo, "background-color"), _cor_do_estilo(estilo, "color"))
            )

        if not any(texto for texto, _, _ in dados):
            continue

        eh_cabecalho = _TEXTO_CABECALHO in " ".join(texto for texto, _, _ in dados).lower()
        for coluna, (texto, cor_fundo, cor_texto) in enumerate(dados, start=1):
            celula = planilha.cell(row=linha_atual, column=coluna, value=texto)
            if eh_cabecalho:
                celula.font = Font(bold=True, color="FFFFFF")
                celula.fill = PatternFill("solid", fgColor=COR_CABECALHO)
            else:
                if cor_fundo and cor_fundo != "TRANSPARENT":
                    celula.fill = PatternFill("solid", fgColor="FF" + cor_fundo)
                if cor_texto:
                    celula.font = Font(color="FF" + cor_texto)
            celula.alignment = Alignment(vertical="top", wrap_text=not eh_cabecalho)

        if eh_cabecalho and not cabecalho_marcado:
            planilha.freeze_panes = f"A{linha_atual + 1}"
            cabecalho_marcado = True
            for coluna in range(1, len(dados) + 1):
                planilha.column_dimensions[get_column_letter(coluna)].width = _LARGURA_COLUNA_PADRAO

        linha_atual += 1

    return workbook
