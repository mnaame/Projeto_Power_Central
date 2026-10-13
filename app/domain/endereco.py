"""Lê bairro e cidade de um endereço escrito por gente.

Camada pura, sem rede. O cadastro da Auvo guarda o endereço inteiro num
campo de texto só, e quem preencheu usou a forma que quis. Dos endereços
reais da base, estes são os formatos que aparecem de verdade:

    Rua João Monlevade,109,,Jardim Leblon,Belo Horizonte,MG,31540280
    RUA SEBASTIAO POSSADA BRAVO,30,LETRA A,SANTA ROSA,Belo Horizonte,MG,31.255-760
    R. Plutão, 144 - Santa Lúcia, Belo Horizonte - MG, 30360-450
    Rua Miranda Ribeiro, 225, Vila Paris, Belo Horizonte - MG, 30380-660, Brasil
    Br 040 Km 688, Ceasa-Pav F Box 40, Kennedy, Contagem-MG
    Multi Formato Distribuidora S.A., Contagem - MG, 32150-245, Brazil
    Acrópoluz Soluções em Iluminação

**A leitura é de trás para frente**, e esse é o ponto do módulo. O começo
do endereço é imprevisível (tem logradouro, tem nome de empresa, tem "Br
040 Km 688", tem vírgula no meio do nome da rua), mas o fim é
disciplinado: país, CEP, UF, cidade, bairro — nessa ordem, cada um
reconhecível pela própria forma. Descascando a cauda, o bairro é o que
sobra na ponta.

O que NÃO dá para ler fica `None`, de propósito: inventar bairro é pior
que admitir que não sabe, porque manda o técnico para a região errada e
ninguém desconfia.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# "30360-450", "31540280", "31.255-760" — o ponto aparece no cadastro real.
RE_CEP = re.compile(r"^\d{2}\.?\d{3}-?\d{3}$")
# "Belo Horizonte - MG", "Contagem-MG", "Lagoa Santa / MG"
RE_CIDADE_UF = re.compile(r"^(.+?)\s*[-/]\s*([A-Za-z]{2})$")

# A lista real, e não "duas letras": o cadastro tem "Economart Escritório
# - BH", que por `[A-Za-z]{2}` virava cidade "Economart Escritório" no
# estado "BH". Uma sigla inventada não pode passar por UF.
UFS = frozenset(
    "AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS "
    "SC SE SP TO".split()
)


def e_uf(texto: str) -> bool:
    """Uma única porta para os dois formatos em que a UF aparece ("...,
    MG, 30100000" e "Belo Horizonte - MG"). Duas checagens iguais em
    lugares diferentes é como uma delas acaba esquecida numa correção."""
    return str(texto or "").strip().upper() in UFS

PAISES = ("BRASIL", "BRAZIL", "BR")

# Caudas que não são bairro nem cidade: o cadastro às vezes termina em
# "S/N", "Brasil", ou no complemento.
RUIDO = ("S/N", "SN", "-", "--", "0")


@dataclass(frozen=True)
class Endereco:
    """O que deu para ler. Campo que não deu fica `None`."""

    bairro: str | None = None
    cidade: str | None = None
    uf: str | None = None
    cep: str | None = None

    def __bool__(self) -> bool:  # "achei alguma coisa?"
        return any((self.bairro, self.cidade, self.uf, self.cep))


def normalizar(texto: str) -> str:
    """Maiúsculas, sem acento, sem espaço sobrando — a régua para comparar
    bairro, que no cadastro aparece como "Padre Eustáquio", "PADRE
    EUSTAQUIO" e "padre eustáquio" para o mesmo lugar."""
    sem_acento = "".join(
        c
        for c in unicodedata.normalize("NFD", (texto or "").upper())
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(sem_acento.split())


def _partes(bruto: str) -> list[str]:
    """Quebra só por vírgula.

    O " - " **não** entra aqui, e isso é deliberado: ele aparece dentro de
    nome de bairro ("Palmares - 4ª Seção (Parque Durval de Barros)"), e
    quebrar por ele cortava o bairro ao meio. Onde o " - " realmente
    separa — "Belo Horizonte - MG" e "144 - Santa Lúcia" — ele é tratado
    no ponto exato em que aparece, e não no atacado."""
    return [p.strip() for p in str(bruto or "").split(",")]


# "RUA", "R.", "AV", "AVENIDA", "ROD", "TRAVESSA"... — se a ponta é um
# logradouro, o cadastro não tem bairro; o que ela tem é a rua repetida.
RE_LOGRADOURO = re.compile(
    r"^(R|RUA|AV|AVE|AVENIDA|ROD|RODOVIA|TRAV|TRAVESSA|AL|ALAMEDA|PCA|PRACA|"
    r"ESTR|ESTRADA|BR)\b",
)


def _limpar_bairro(candidato: str) -> str | None:
    """A ponta que sobrou é mesmo um bairro?

    Três coisas se disfarçam de bairro no cadastro real e precisam ser
    recusadas, porque um bairro inventado manda o técnico para a região
    errada sem ninguém desconfiar:

    - **número** ("2350", "18"): é o número da casa de um endereço que
      simplesmente não tem bairro;
    - **logradouro** ("Rua N Senora do Perpetuo Socorro"): é a rua de novo;
    - **número colado no bairro** ("144 - Santa Lúcia"): aqui o bairro
      existe, é só descartar o número da frente — e por isso este caso
      limpa em vez de recusar."""
    pedacos = [p.strip() for p in re.split(r"\s+-\s+", candidato) if p.strip()]
    while len(pedacos) > 1 and pedacos[0].isdigit():
        pedacos.pop(0)
    limpo = " - ".join(pedacos).strip()

    # Número colado no começo, separado só por espaço ("592 Curralinho").
    # Exige dígito puro: "4ª Seção" começa com número e é nome de bairro
    # de verdade, então o "ª" é o que separa um caso do outro.
    primeira, _, resto = limpo.partition(" ")
    if resto and primeira.isdigit():
        limpo = resto.strip()

    if not limpo or limpo.isdigit():
        return None
    if RE_LOGRADOURO.match(normalizar(limpo)):
        return None
    return limpo


def _e_ruido(parte: str) -> bool:
    return normalizar(parte) in RUIDO or not parte


def ler(bruto: object) -> Endereco:
    """Lê o endereço de trás para frente, descascando o que se identifica
    sozinho: país, CEP, UF (ou "Cidade - UF"), cidade. O que sobrar na
    ponta é o bairro."""
    partes = [p for p in _partes(bruto) if not _e_ruido(p)]
    if not partes:
        return Endereco()

    cep = uf = cidade = None

    # "Brasil", mas também "Brasil - escola" e "Brazil - galpao": alguém
    # pendurou o tipo do imóvel no fim do endereço. O que decide é o
    # começo do pedaço, senão esse rabo vira nome de bairro.
    if normalizar(re.split(r"\s+-\s+", partes[-1])[0]) in PAISES:
        partes.pop()
    if partes and RE_CEP.match(partes[-1]):
        cep = partes.pop().replace(".", "")
    if partes and e_uf(partes[-1]):
        uf = partes.pop().upper()
        if partes:
            cidade = partes.pop()
    elif (
        partes
        and (casado := RE_CIDADE_UF.match(partes[-1]))
        and e_uf(casado.group(2))
    ):
        # "Belo Horizonte - MG" num pedaço só — o `_partes` já teria
        # quebrado no " - ", então aqui cai o caso colado ("Contagem-MG").
        partes.pop()
        cidade, uf = casado.group(1).strip(), casado.group(2).upper()

    # Sobrou pelo menos o logradouro além do bairro? Só então a ponta é
    # bairro. Um endereço de uma linha só ("Acrópoluz Soluções em
    # Iluminação") não tem bairro nenhum, e chutar que tem seria inventar.
    bairro = _limpar_bairro(partes[-1]) if len(partes) >= 2 else None

    return Endereco(bairro=bairro, cidade=cidade or None, uf=uf, cep=cep)


def bairro_de(bruto: object) -> str | None:
    return ler(bruto).bairro


# Partículas que não levam maiúscula no meio de um nome brasileiro.
MINUSCULAS = {"DE", "DA", "DO", "DAS", "DOS", "E", "D"}


def titulo(texto: str) -> str:
    """"ESTORIL" e "Estoril" têm que virar a mesma coisa na tela.

    Sem isto, o mesmo bairro grafado de dois jeitos no cadastro aparece
    como duas regiões, e a equipe sai em duas visitas para o mesmo lugar.
    Palavra que não é alfabética ("4ª", "(Parque") fica como está — não há
    o que normalizar nela, e mexer só estragaria."""
    palavras = []
    for indice, palavra in enumerate(str(texto or "").split()):
        if not palavra.isalpha():
            palavras.append(palavra)
        elif indice > 0 and palavra.upper() in MINUSCULAS:
            palavras.append(palavra.lower())
        else:
            palavras.append(palavra[0].upper() + palavra[1:].lower())
    return " ".join(palavras)


def chave_regiao(bairro: str | None, cidade: str | None) -> str:
    """A chave de agrupamento: sem acento, sem caixa, sem espaço sobrando.

    É ela que junta "ESTORIL" com "Estoril" e "SÃO LUCAS" com "Sao
    Lucas" — grafias que convivem no mesmo cadastro."""
    return f"{normalizar(bairro or '')}|{normalizar(cidade or '')}"


def rotulo_regiao(bairro: str | None, cidade: str | None) -> str:
    """Como a região aparece na tela e no Excel.

    Bairro sozinho seria ambíguo entre cidades — "Centro" existe em Belo
    Horizonte, em Contagem e em Betim, e juntá-los numa região só mandaria
    o técnico atravessar a região metropolitana achando que era uma saída
    só."""
    bairro = titulo((bairro or "").strip())
    cidade = titulo((cidade or "").strip())
    if bairro and cidade:
        return f"{bairro} — {cidade}"
    return bairro or cidade or ""
