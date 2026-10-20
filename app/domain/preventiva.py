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
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

# Códigos de zona que não são sensor físico. O critério principal é ser
# **não-numérico** — o cadastro usa 1..N para os sensores e letras para o
# resto; os prefixos são a rede de segurança configurável.
PREFIXOS_ESPECIAIS_PADRAO: tuple[str, ...] = ("SP", "NO")


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

    O casamento é pela **descrição normalizada**, não pelo código: o
    evento traz o nome da zona, não o número dela."""
    primeiro_evento: dict[str, str] = {}
    for evento in eventos:
        descricao = normalizar(str(evento.get("zona") or ""))
        if not descricao:
            continue
        quando = str(evento.get("quando") or "")
        # O export vem em ordem decrescente de data, então a última linha
        # vista de cada zona é a mais antiga — o PRIMEIRO disparo dela.
        if descricao not in primeiro_evento or (
            quando and quando < primeiro_evento[descricao]
        ):
            primeiro_evento[descricao] = quando

    resultado = Resultado()
    vistas: set[str] = set()

    for zona in zonas_cadastro:
        codigo = str(getattr(zona, "codigo", "")).strip()
        descricao = str(getattr(zona, "descricao", "")).strip()
        chave = normalizar(descricao)
        quando = primeiro_evento.get(chave, "")
        if chave:
            vistas.add(chave)

        conferida = ZonaConferida(codigo=codigo, descricao=descricao, quando=quando)
        if e_especial(codigo, prefixos=prefixos_especiais):
            resultado.ignoradas.append(conferida)
        elif quando or chave in primeiro_evento:
            resultado.dispararam.append(conferida)
        else:
            resultado.faltam.append(conferida)

    resultado.extras = sorted(set(primeiro_evento) - vistas)

    for lista in (resultado.dispararam, resultado.faltam, resultado.ignoradas):
        lista.sort(key=lambda z: z.ordem)
    return resultado


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

    if resultado.extras:
        # Não é erro do técnico: é zoneamento desatualizado, e some da
        # tela se ninguém mostrar.
        linhas.append(
            "Dispararam e NÃO estão no zoneamento: " + ", ".join(resultado.extras)
        )

    return "\n".join(linhas)
