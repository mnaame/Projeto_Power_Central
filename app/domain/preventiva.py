"""Conferência da preventiva: quais zonas ainda não dispararam.

Camada pura, sem rede. Cruza o **zoneamento cadastrado** com o que
**chegou de evento** na janela da visita, e diz o que falta testar.

**Para que serve.** Na preventiva o técnico percorre a loja acionando
sensor por sensor. Conferir na mão, no fim, quais dos quinze já
apareceram na central é trabalhoso e é onde escapa o sensor morto — que
é justamente o que a preventiva existe para achar.

**O erro que este módulo não pode cometer.** Dizer "FALTA" para uma zona
que disparou manda o técnico voltar a uma loja pronta, e — pior — ensina
a equipe a desconfiar do relatório. Daí duas decisões:

1. **Qualquer evento que carregue uma zona conta.** Não se filtra por um
   código específico: uma porta magnética gera `NYR`, não `BUR`, e um
   painel pode gerar outra coisa ainda. O que importa é que a central
   recebeu alguma coisa daquela zona.
2. **Zona especial não entra no "faltam".** `SP1 SOS-PÂNICO` e `SP2
   INCÊNDIO` não se aciona em rotina; contá-las como pendência faria todo
   relatório terminar com um "faltam 2" permanente, e um alerta que nunca
   zera é um alerta que ninguém lê.
3. **O código entra no cruzamento, não só o nome.** O relatório escreve a
   zona como `(26) IVP ENTRADA NOVA` — número e descrição no mesmo
   texto — enquanto o cadastro guarda `26` e `IVP ENTRADA NOVA` em campos
   separados. Comparar os textos crus não casa **nenhuma** zona: a
   primeira preventiva real saiu "0 de 9 dispararam" com as mesmas nove
   zonas listadas logo abaixo como "dispararam e não estão no
   zoneamento". É o modo de falhar mais caro que este módulo tem, porque
   parece um relatório preenchido.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

# Códigos de zona que não são sensor físico. O critério principal é ser
# **não-numérico** — o cadastro usa 1..N para os sensores e letras para o
# resto; os prefixos são a rede de segurança configurável.
PREFIXOS_ESPECIAIS_PADRAO: tuple[str, ...] = ("SP", "NO")

# "(26) IVP ENTRADA NOVA" -> código "26", descrição "IVP ENTRADA NOVA".
#
# **Só dígito.** O relatório escreve o número da zona entre parênteses, e
# aceitar qualquer texto curto ali custaria caro: uma zona cadastrada como
# "(FUNDOS) PORTA" passaria a casar com uma zona chamada só "PORTA", dando
# OK para um sensor que ninguém acionou. Zona especial não se parte — ela é
# ignorada de qualquer forma.
_RE_CODIGO_ENTRE_PARENTESES = re.compile(r"^\(\s*(\d{1,6})\s*\)\s*(.*)$")


def normalizar(texto: str) -> str:
    """Maiúsculas, sem acento, sem espaço sobrando.

    É a régua do cruzamento: o cadastro grava "Infra Sala" e o evento
    pode chegar "INFRA SALA" ou "INFRA  SALA". Comparar cru reprovaria a
    zona por causa de um espaço."""
    sem_acento = "".join(
        c
        for c in unicodedata.normalize("NFD", (texto or "").upper())
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(sem_acento.split())


def partir_zona(texto: str) -> tuple[str, str]:
    """Separa `"(26) IVP ENTRADA NOVA"` em `("26", "IVP ENTRADA NOVA")`.

    Sem parênteses na frente, devolve `("", texto)` — o texto inteiro é a
    descrição."""
    limpo = (texto or "").strip()
    casou = _RE_CODIGO_ENTRE_PARENTESES.match(limpo)
    if not casou:
        return "", limpo
    return casou.group(1).strip(), casou.group(2).strip()


def _chave_descricao(texto: str) -> str:
    """A descrição normalizada por que um texto de zona casa: o texto sem
    o `(NN) ` da frente.

    A mesma regra vale nos dois lados, e é o que torna o cruzamento
    simétrico sem precisar saber de antemão qual deles escreve o número.
    Também garante que isto nunca é **menos** generoso que comparar os
    textos crus: dois textos iguais continuam iguais depois de tirar o
    mesmo prefixo."""
    _, resto = partir_zona(texto)
    return normalizar(resto)


def e_especial(
    codigo: str, *, prefixos: Sequence[str] = PREFIXOS_ESPECIAIS_PADRAO
) -> bool:
    """Zona que não se testa em rotina.

    Não-numérica basta: o cadastro numera os sensores físicos e reserva
    letras para pânico, incêndio e afins."""
    limpo = (codigo or "").strip()
    if not limpo:
        return True
    if not limpo.isdigit():
        return True
    normalizado = normalizar(limpo)
    return any(normalizado.startswith(normalizar(p)) for p in prefixos if p.strip())


@dataclass(frozen=True)
class ZonaConferida:
    """Uma zona do cadastro, com o que se descobriu dela na janela."""

    codigo: str
    descricao: str
    quando: str = ""  # hora do primeiro evento, vazio se não apareceu

    @property
    def rotulo(self) -> str:
        return f"{self.codigo} {self.descricao}".strip()

    @property
    def ordem(self) -> tuple[int, int, str]:
        """Numéricas em ordem numérica, as outras no fim em ordem
        alfabética. Ordenar "10" depois de "9" como texto poria a 10
        antes da 2, e a lista é conferida contra a loja na ordem dos
        sensores."""
        limpo = self.codigo.strip()
        if limpo.isdigit():
            return (0, int(limpo), "")
        return (1, 0, normalizar(limpo))


@dataclass
class Resultado:
    """O que a conferência achou."""

    dispararam: list[ZonaConferida] = field(default_factory=list)
    faltam: list[ZonaConferida] = field(default_factory=list)
    ignoradas: list[ZonaConferida] = field(default_factory=list)
    # Zona que apareceu no evento e não está no cadastro. Costuma ser
    # zoneamento desatualizado, e aparecer na tela é o que faz alguém
    # arrumar.
    extras: list[str] = field(default_factory=list)
    # Zona que casou pelo NÚMERO mas com nome diferente do cadastrado. É o
    # único casamento deste módulo que pode estar errado (se o número entre
    # parênteses não for o código da zona), então ele não passa calado: sai
    # na mensagem para alguém olhar.
    divergentes: list[str] = field(default_factory=list)

    @property
    def total_fisicas(self) -> int:
        return len(self.dispararam) + len(self.faltam)

    @property
    def completa(self) -> bool:
        return self.total_fisicas > 0 and not self.faltam


def conferir(
    zonas_cadastro: Iterable,
    eventos: Iterable[Mapping[str, object]],
    *,
    prefixos_especiais: Sequence[str] = PREFIXOS_ESPECIAIS_PADRAO,
) -> Resultado:
    """Cruza cadastro × eventos.

    `zonas_cadastro` são os objetos de `domain/zoneamento` (código,
    descrição); `eventos` são dicionários com `zona` e `quando` — o que
    `tecnico.zonas_do_export` devolve.

    **O casamento é por código OU por descrição**, qualquer um dos dois
    bastando. O relatório escreve `(26) IVP ENTRADA NOVA` num só campo e
    o cadastro guarda `26` e `IVP ENTRADA NOVA` separados: exigir os dois
    não casaria nada, e olhar só a descrição foi o que fez a primeira
    preventiva real reprovar as nove zonas que haviam disparado.

    Código igual é sinal forte o bastante sozinho — zona 3 é zona 3,
    mesmo que alguém tenha renomeado a descrição e o zoneamento esteja
    desatualizado."""
    disparos = _agrupar_disparos(eventos)

    # Índices para o cruzamento. `set` de chaves, e não uma chave só, para
    # não perder um disparo quando dois rótulos diferentes apontam para a
    # mesma descrição.
    por_codigo: dict[str, set[str]] = {}
    por_descricao: dict[str, set[str]] = {}
    for chave, dado in disparos.items():
        if dado["codigo"]:
            por_codigo.setdefault(dado["codigo"], set()).add(chave)
        for descricao in dado["descricoes"]:
            por_descricao.setdefault(descricao, set()).add(chave)

    resultado = Resultado()
    casadas: set[str] = set()

    for zona in zonas_cadastro:
        codigo = str(getattr(zona, "codigo", "")).strip()
        descricao = str(getattr(zona, "descricao", "")).strip()

        chave_cadastro = _chave_descricao(descricao)
        candidatas = set(por_codigo.get(normalizar(codigo), ()))
        if chave_cadastro:
            candidatas |= por_descricao.get(chave_cadastro, set())
        casadas |= candidatas

        # Entre os disparos que casaram, vale o mais antigo: é a hora em
        # que o técnico acionou o sensor.
        quando = min(
            (disparos[c]["quando"] for c in candidatas if disparos[c]["quando"]),
            default="",
        )

        conferida = ZonaConferida(codigo=codigo, descricao=descricao, quando=quando)
        if e_especial(codigo, prefixos=prefixos_especiais):
            resultado.ignoradas.append(conferida)
        elif candidatas:
            resultado.dispararam.append(conferida)
            if not any(chave_cadastro in disparos[c]["descricoes"] for c in candidatas):
                rotulos = ", ".join(sorted(disparos[c]["rotulo"] for c in candidatas))
                resultado.divergentes.append(f"{conferida.rotulo} = {rotulos}")
        else:
            resultado.faltam.append(conferida)

    # Sobra do cruzamento: zona que disparou e o cadastro não conhece.
    # Mostra-se o rótulo como veio do relatório, que é o que se procura na
    # plataforma para arrumar o zoneamento.
    resultado.extras = [
        dado["rotulo"]
        for chave, dado in sorted(
            disparos.items(), key=lambda par: _ordem_disparo(par[1])
        )
        if chave not in casadas
    ]

    for lista in (resultado.dispararam, resultado.faltam, resultado.ignoradas):
        lista.sort(key=lambda z: z.ordem)
    return resultado


def _agrupar_disparos(eventos: Iterable[Mapping[str, object]]) -> dict[str, dict]:
    """Uma entrada por zona vista nos eventos, com o primeiro horário.

    Agrupa pelo **código**, quando o rótulo traz um: `(4) RECEPÇÃO` e
    `(4) RECEPCAO` são o mesmo sensor e não podem virar duas linhas de
    "disparou e não está no zoneamento"."""
    disparos: dict[str, dict] = {}
    for evento in eventos:
        rotulo = str(evento.get("zona") or "").strip()
        if not rotulo:
            continue
        codigo, _ = partir_zona(rotulo)
        codigo = normalizar(codigo)
        descricao = _chave_descricao(rotulo)
        if not codigo and not descricao:
            continue

        # O `#` impede que um código colida com uma descrição homônima.
        chave = f"#{codigo}" if codigo else descricao
        atual = disparos.setdefault(
            chave,
            {"rotulo": rotulo, "codigo": codigo, "quando": "", "descricoes": set()},
        )
        if descricao:
            atual["descricoes"].add(descricao)

        # O export vem em ordem decrescente de data, mas não se depende
        # disso: guarda-se o menor horário preenchido, que é o PRIMEIRO
        # disparo da zona.
        quando = str(evento.get("quando") or "")
        if quando and (not atual["quando"] or quando < atual["quando"]):
            atual["quando"] = quando
    return disparos


def _ordem_disparo(dado: Mapping[str, object]) -> tuple[int, int, str]:
    """Mesma régua de `ZonaConferida.ordem`: numéricas em ordem numérica,
    o resto no fim. Sem isso a zona 30 sai antes da 4."""
    codigo = str(dado.get("codigo") or "")
    if codigo.isdigit():
        return (0, int(codigo), "")
    return (1, 0, normalizar(str(dado.get("rotulo") or "")))


def _hora_curta(quando: str) -> str:
    """"2026-10-20T14:32:00" -> "14:32". Em preventiva do mesmo dia a
    data é ruído."""
    if "T" in quando and len(quando) >= 16:
        return quando[11:16]
    return ""


def formatar_preventiva(
    resultado: Resultado,
    *,
    numero_conta: str,
    nome_cliente: str,
    horas: int,
    com_horario: bool = False,
) -> str:
    """Texto do Telegram. Curto de propósito: é lido no celular, dentro
    da loja, com o técnico de pé."""
    linhas = [
        f"Preventiva — {numero_conta} {nome_cliente} (últimas {horas}h)".strip()
    ]

    if not resultado.total_fisicas:
        linhas.append(
            "Esta conta não tem zona física cadastrada — não há o que conferir."
        )
        if resultado.ignoradas:
            linhas.append(
                "Especiais: " + ", ".join(z.rotulo for z in resultado.ignoradas)
            )
        return "\n".join(linhas)

    linhas.append(
        f"Dispararam: {len(resultado.dispararam)} de "
        f"{resultado.total_fisicas} zonas físicas"
    )

    if resultado.dispararam:
        def _ok(zona: ZonaConferida) -> str:
            hora = _hora_curta(zona.quando) if com_horario else ""
            return f"{zona.rotulo} ({hora})" if hora else zona.rotulo

        linhas.append("OK: " + ", ".join(_ok(z) for z in resultado.dispararam))

    if resultado.faltam:
        linhas.append(
            f"FALTAM ({len(resultado.faltam)}): "
            + ", ".join(z.rotulo for z in resultado.faltam)
        )
    else:
        linhas.append("FALTAM: nenhuma — preventiva completa.")

    if resultado.ignoradas:
        linhas.append(
            "Especiais ignoradas: "
            + ", ".join(z.rotulo for z in resultado.ignoradas)
        )

    if resultado.divergentes:
        # Casou pelo número, com nome diferente. Dar OK aqui é a única
        # aposta que este módulo faz — mostrá-la é o que permite desmenti-la.
        linhas.append(
            "Nome diferente do zoneamento (casou pelo número): "
            + "; ".join(resultado.divergentes)
        )

    if resultado.extras:
        # Não é erro do técnico: é zoneamento desatualizado, e some da
        # tela se ninguém mostrar.
        linhas.append(
            "Dispararam e NÃO estão no zoneamento: " + ", ".join(resultado.extras)
        )

    return "\n".join(linhas)
