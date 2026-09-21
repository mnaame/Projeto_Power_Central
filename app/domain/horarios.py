"""Auditoria de horários de arme/desarme. Camada pura — sem I/O.

A regra central é de uma linha só: **conta sem nenhuma linha de horário é
conta sem horário cadastrado**. O resto deste módulo existe por causa do
tipo da conta, que é o que separa "falta cadastrar" de "não precisa":
residência normalmente não tem arme programado, comércio tem.

Sobre os nomes dos campos de tipo: o `CuentaByDealer` identifica o tipo
por número (é o mesmo campo que o filtro da tela "Falha TST" usa em
`_tip_nTipo`), e a descrição legível vem do catálogo
`t_CuentasTipoServicio`. Como o portal varia a grafia dos campos entre
telas, a leitura aqui é tolerante: procura por uma lista de nomes
candidatos, sem diferenciar maiúscula de minúscula. Campo que não existe
não vira erro — vira tipo desconhecido, e conta com tipo desconhecido
nunca é escondida por filtro (ver `filtrar_por_tipo`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

# Tipo desconhecido: a conta existe, mas o portal não disse o que ela é.
TIPO_DESCONHECIDO = "—"

# Nomes candidatos para o tipo na linha da conta, do mais provável para o
# menos. Comparados em minúsculas contra as chaves da linha.
CAMPOS_TIPO_TEXTO = (
    "tip_cdescripcion",
    "tip_cnombre",
    "tipo_descripcion",
    "cue_ctipo",
    "tipo",
)
CAMPOS_TIPO_NUMERO = ("_tip_ntipo", "tip_ntipo", "cue_itipo", "cue_ntipo")

# Catálogo: id -> descrição.
CAMPOS_CATALOGO_ID = ("id", "tip_ntipo", "tip_iid", "value")
CAMPOS_CATALOGO_NOME = ("tip_cdescripcion", "tip_cnombre", "descripcion", "nombre", "text")


@dataclass(frozen=True)
class ContaAuditada:
    """Uma conta já classificada pela varredura."""

    conta: str
    nome: str
    tipo: str
    resumo: str = ""
    erro: str = ""

    @property
    def rotulo(self) -> str:
        return f"{self.conta} — {self.nome}"


def _texto(valor: object) -> str:
    return str(valor).strip() if valor is not None else ""


def _primeiro_campo(linha: Mapping[str, object], candidatos: Sequence[str]) -> str:
    """Primeiro candidato presente na linha, comparando sem case. Devolve
    string vazia quando nenhum existe — o portal muda a grafia entre telas
    e um campo ausente não pode derrubar a varredura."""
    normalizada = {str(chave).strip().lower(): valor for chave, valor in linha.items()}
    for candidato in candidatos:
        valor = normalizada.get(candidato)
        if valor is not None and _texto(valor) != "":
            return _texto(valor)
    return ""


def tem_horario(rows: Sequence[Mapping[str, object]]) -> bool:
    """A regra do módulo: nenhuma linha = nenhum horário cadastrado."""
    return bool(rows)


def resumo_horario(rows: Sequence[Mapping[str, object]]) -> str:
    """Contagem + primeira faixa legível, para a coluna de referência da
    lista "com horário". Não tenta reconstruir a grade inteira: quem
    precisa do detalhe abre a conta no portal."""
    if not rows:
        return ""
    primeira = rows[0]
    abertura = _texto(primeira.get("hor_choraapertura"))
    fechamento = _texto(primeira.get("hor_choracierre"))
    faixa = f"{abertura}–{fechamento}" if abertura or fechamento else ""
    return f"{len(rows)} faixa(s) {faixa}".strip()


def catalogo_de_tipos(linhas: Sequence[Mapping[str, object]]) -> dict[str, str]:
    """`t_CuentasTipoServicio` -> {id: descrição}. Linha sem id ou sem
    descrição é ignorada em vez de virar entrada inútil."""
    catalogo: dict[str, str] = {}
    for linha in linhas:
        identificador = _primeiro_campo(linha, CAMPOS_CATALOGO_ID)
        descricao = _primeiro_campo(linha, CAMPOS_CATALOGO_NOME)
        if identificador and descricao:
            catalogo[identificador] = descricao
    return catalogo


def tipo_da_conta(linha: Mapping[str, object], catalogo: Mapping[str, str] | None = None) -> str:
    """Tipo legível da conta, ou `TIPO_DESCONHECIDO`.

    Ordem de tentativa: descrição que já veio na própria linha; senão o
    número da linha traduzido pelo catálogo. Número sem tradução fica
    desconhecido de propósito — mostrar "4" na tela não ajuda ninguém a
    decidir se a conta precisa de horário."""
    descricao = _primeiro_campo(linha, CAMPOS_TIPO_TEXTO)
    if descricao:
        return descricao

    numero = _primeiro_campo(linha, CAMPOS_TIPO_NUMERO)
    if numero and catalogo:
        # O portal devolve o id ora como "4", ora como "4.0".
        for chave in (numero, numero.split(".")[0]):
            if chave in catalogo:
                return catalogo[chave]
    return TIPO_DESCONHECIDO


def tipo_aceito(item: ContaAuditada, tipos: Sequence[str]) -> bool:
    """**Conta de tipo desconhecido passa sempre.** Se o portal não disse o
    que a conta é, escondê-la de um filtro "Comercial" seria transformar
    uma limitação da integração em conta auditada por engano — e o objetivo
    do módulo é justamente não deixar conta passar batido. `tipos` vazio
    também não filtra nada."""
    desejados = {t.strip().lower() for t in tipos if t.strip()}
    if not desejados:
        return True
    return item.tipo == TIPO_DESCONHECIDO or item.tipo.strip().lower() in desejados


def nome_casa(item: ContaAuditada, busca: str) -> bool:
    """Busca livre por número ou nome — é o recorte que continua
    funcionando mesmo quando o portal não entrega o tipo de conta."""
    termo = (busca or "").strip().lower()
    if not termo:
        return True
    return termo in item.nome.lower() or termo in item.conta.lower()


def filtrar_por_tipo(itens: Sequence[ContaAuditada], tipos: Sequence[str]) -> list[ContaAuditada]:
    return [i for i in itens if tipo_aceito(i, tipos)]


def filtrar_por_nome(itens: Sequence[ContaAuditada], busca: str) -> list[ContaAuditada]:
    return [i for i in itens if nome_casa(i, busca)]
