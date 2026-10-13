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
nela, o cliente não entra em rota nenhuma.

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

Validado com a base real (13/10): 106 clientes base, 100 com coordenada →
35 rotas a 1,5 km.
