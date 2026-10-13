# Módulo: Rotas de Visita Preventiva

Extensão de [`ARQUITETURA.md`](ARQUITETURA.md). Agrupa os clientes **base**
por proximidade geográfica para agendar as visitas preventivas por região.
**Só leitura** — não escreve nada na PowerCentral nem na Auvo.

## 1. Quem é "base"

Tudo que não é Villefort, Super Nosso/Apoio nem conta interna
(`NOVO MILLENIUM`, `CONTA TESTE`). A classificação de grupo é a de
`disparos_geral.grupo_do_cliente`, **reaproveitada inteira** — ter duas
definições de "quem é Villefort" no sistema seria o começo de dois números
diferentes para a mesma pergunta.

## 2. De onde vem a coordenada

Duas fontes, com confiabilidades diferentes:

1. **Auvo** (preferida) — é o app que o técnico usa em campo, então a
   coordenada foi conferida por alguém que esteve no local.
2. **PowerCentral** (reserva) — a "Localização da conta", no formato
   `"lat,long"`, e só com a **região validada**.

O casamento entre as bases é por `AuvoDepara` com status **OK** e, na
falta, por nome com corte alto (0,88). Nessa ordem de propósito: o de-para
foi confirmado por uma pessoa, o nome é palpite calculado. `REVISAR` nunca
entra — casamento não confirmado mandaria o técnico para o endereço de
outro cliente.

### A coordenada é achada pela forma, não pelo nome do campo

`rotas.coordenada_do_registro` varre o registro inteiro: primeiro campos
chamados `latitude`/`longitude` (e `lat`/`lng`), depois qualquer campo de
texto com um par `"lat,long"`, depois os sub-registros. Aceita vírgula
como decimal (`-19,8435179`, que é como a Auvo entrega) e vírgula nos dois
papéis (`-19,9191,-43,9386`).

Isso **não** é flexibilidade decorativa, é a correção de um bug que
custou uma rodada inteira. A primeira versão procurava a localização da
conta em `cue_clocalizacion` — nome chutado, errado — e o resultado foi
*105 clientes base, 0 com coordenada, 0 Auvo · 0 Power*: zero absoluto,
sem um único erro na tela, porque para um `.get()` "campo ausente" e
"campo vazio" são a mesma coisa. Um par de coordenadas se identifica
sozinho; o nome do campo é detalhe de cada plataforma.

Quem impede um par de números qualquer (um CEP, um valor) de passar por
coordenada é a caixa da região, logo abaixo — não o nome do campo.

O resumo da tela mostra as três etapas do caminho da Auvo (clientes
lidos → com lat/long na região → casados com uma conta base). Sem elas,
um "0 Auvo" não distingue Auvo fora do ar de nome que não casou de
cadastro sem lat/long, que foi exatamente o que travou o diagnóstico na
primeira rodada.

### Por que validar a região

Parte das coordenadas do cadastro aponta para outro estado. Uma coordenada
errada **não atrapalha só a si mesma**: ela entra num cluster e distorce o
centroide, levando a rota inteira para o lugar errado. Por isso a caixa
delimitadora (MG/BH: lat −21,5..−18,5 · lon −45,5..−43,0) é checada
**antes** de agrupar, e o que cai fora é tratado como sem coordenada.

`(0, 0)` — a "ilha nula", que é o que um cadastro vazio vira — também é
descartado; tratá-la como coordenada colocaria o cliente no Atlântico.

Cliente sem coordenada em nenhuma fonte vai para a lista **"sem
coordenada"**, que é a lista de trabalho do cadastro: enquanto estiver
nela, o cliente não entra em rota nenhuma. O motivo de cada linha diz
onde consertar — não casou na Auvo, casou mas o cadastro lá está sem
lat/long, ou a Auvo estava fora. "Sem coordenada" sozinho não é
acionável.

## 3. Agrupamento (`app/domain/rotas.py`, puro)

- **Distância**: haversine. É linha reta, não distância de rua — e não
  precisa ser: serve para dizer quem está perto de quem, e a ordem de
  grandeza do erro não muda o agrupamento.
- **Clusters por limiar** (union-find), raio configurável
  (`rotas_raio_km`, padrão 1,5 km). A proximidade é **transitiva**: A perto
  de B, B perto de C ⇒ os três na mesma rota. É o comportamento certo para
  clientes enfileirados ao longo de uma avenida.
- **Por que limiar e não "k grupos"**: um k-means exigiria escolher o
  número de rotas, e o número certo não existe — depende de como os
  clientes estão espalhados. O limiar responde à pergunta que a operação
  faz de verdade: "dá para visitar os dois na mesma saída?".
- **Ordem de visita**: vizinho mais próximo a partir do centroide. Não é a
  rota ótima (isso é o caixeiro-viajante) e não precisa ser — o objetivo é
  evitar o zigue-zague de uma lista alfabética.
- **Determinismo**: empate de distância é desempatado pelo número da
  conta. Sem isso, a mesma base saía em ordens diferentes conforme a
  plataforma devolvesse os registros, e a equipe não conseguiria conferir
  nada. Há teste comparando o resultado com a entrada invertida.

  Dois vazamentos só apareceram rodando contra a base real, e os dois
  estão fechados com teste próprio:

  1. `ordenar_visita` devolvia uma rota de **dois** clientes na ordem em
     que ela chegou (curto-circuito `len <= 2`). Quatro rotas saíam
     invertidas. Hoje a dupla passa pelo mesmo caminho das outras.
  2. O centroide somava com `sum`, e **soma de float depende da ordem**
     das parcelas: a mesma rota em outra ordem dava um centroide
     diferente nos últimos bits, o bastante para trocar o ponto de
     partida num empate apertado. Hoje é `math.fsum`, que é exatamente
     arredondado e independente da ordem.

## 4. Mapa

Leaflet **1.9.4 vendorizado** em `static/vendor/leaflet/` (BSD-2), não CDN:
o site roda na rede interna e precisa abrir sem depender de CDN. Só os
tiles vêm do OpenStreetMap — sem internet o mapa fica cinza, mas a página e
as tabelas continuam inteiras.

Os dados chegam ao JS por `data-attribute`, não por uma chamada à API: a
tela já recebeu as rotas renderizadas, e buscar de novo seria refazer uma
consulta que leva minutos. O `leaflet.js` só é carregado quando há rotas na
tela.

## 5. Resiliência

- **Auvo fora do ar não cancela nada**: sobra a coordenada da PowerCentral,
  que cobre parte da base. Entregar metade é melhor que entregar nada — e o
  resumo mostra de onde veio cada coordenada e avisa o que faltou.
- **PowerCentral fora** aborta com erro próprio: sem a lista de contas não
  existe nada para agrupar.
- O resultado fica na sessão entre gerar e exportar, para o Excel sair
  **exatamente** igual ao que está na tela.

## 6. Configuração

| Chave | Padrão | Para quê |
|---|---|---|
| `rotas_raio_km` | `1.5` | Raio do agrupamento. Maior = menos rotas, mais espalhadas |

### Conferir contra as plataformas de verdade

```
.venv\Scripts\python.exe scripts\debug_rotas.py
```

Imprime os **nomes de campo que cada plataforma realmente devolve**,
quantas coordenadas sobrevivem a cada etapa (de-para → nome → Auvo →
Power) e a fila de trabalho do cadastro. É só leitura. Foi escrito depois
do bug do nome de campo chutado: quando um número da tela não fizer
sentido, é por aqui que se descobre em qual etapa ele se perde, em vez de
adivinhar.

## 7. Validação com a base real (13/10)

Simulação do pipeline inteiro contra o export de clientes da Auvo (579
clientes) e o relatório de contas da PowerCentral (148 contas):

| | |
|---|---|
| Clientes base | **106** |
| Casaram com um cliente da Auvo (nome, corte 0,88) | 79 |
| Coordenada vinda da Auvo | **77** |
| Coordenada vinda da PowerCentral | **23** |
| Sem coordenada em nenhuma fonte | **6** |

Dos 6, cinco não casaram com nenhum cliente da Auvo e um casou mas está
sem lat/long lá.

Rotas por raio: 51 a 1 km · **35 a 1,5 km** · 15 a 3 km · 7 a 5 km. De 3
km para cima uma rota única engole 79 dos 100 clientes — é o sinal de que
o raio passou do ponto de ser uma "saída".

Sobre a caixa da região: das 104 contas base que têm par de coordenadas
no cadastro da PowerCentral, **13 caem fora de MG/BH** (apontam para
o interior de São Paulo). Sem o descarte, cada uma dessas arrastaria o
centroide da sua rota.
