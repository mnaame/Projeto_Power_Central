# Módulo: Visita Preventiva por Bairro

Extensão de [`ARQUITETURA.md`](ARQUITETURA.md). Cataloga os clientes
**base** por bairro, para agendar as preventivas por região. **Só
leitura** — não escreve nada na PowerCentral nem na Auvo.

## 1. Por que bairro, e não distância

A primeira versão agrupava por raio em quilômetros: haversine, clusters
por limiar, mapa com os pontos. Funcionava, foi testada, e foi
descartada. Dois motivos, nessa ordem:

1. **Dependia da coordenada**, que é justamente o campo que o cadastro
   não tem confiável. Na base real, 13 das 104 contas com coordenada
   apontavam para outro estado.
2. **Respondia uma pergunta que a operação não faz.** Quem monta a agenda
   pensa "quem eu tenho no Padre Eustáquio?", não "quem está a 1,5 km
   deste ponto". Bairro é a unidade que a equipe já usa para falar de
   região, e vem escrito no endereço que o cadastro tem.

O código do agrupamento por distância está no histórico do git, não aqui.

### Bairro sempre com a cidade

"Centro" existe em Belo Horizonte, em Contagem e em Betim. Agrupar só
pelo nome do bairro juntaria clientes a trinta quilômetros um do outro
numa "mesma região" — o erro mais caro que este módulo poderia cometer.
A chave de agrupamento é bairro **+** cidade, normalizada sem acento e
sem caixa, para que "ESTORIL" e "Estoril" não virem duas saídas para o
mesmo lugar.

## 2. Quem é "base"

Tudo que não é Villefort, Super Nosso/Apoio nem conta interna
(`NOVO MILLENIUM`, `CONTA TESTE`). A classificação de grupo é a de
`disparos_geral.grupo_do_cliente`, **reaproveitada inteira** — ter duas
definições de "quem é Villefort" no sistema seria o começo de dois
números diferentes para a mesma pergunta.

## 3. De onde vem o endereço

Quatro fontes, nesta ordem:

| # | Fonte | O que entrega |
|---|---|---|
| 1 | **Auvo ao vivo** (API) | bairro e cidade |
| 2 | **Planilha da Auvo** importada | bairro e cidade |
| 3 | **PowerCentral ao vivo** (API) | normalmente só a cidade |
| 4 | **Planilha da PowerCentral** importada | cidade |

O casamento com a Auvo é por `AuvoDepara` com status **OK** e, na falta,
por nome com corte alto (0,88). Nessa ordem de propósito: o de-para foi
confirmado por uma pessoa, o nome é palpite calculado. `REVISAR` nunca
entra — casamento não confirmado colocaria o cliente no bairro de outro.

### Por que existe importação de planilha

Porque o catálogo **não pode depender de adivinhar nome de campo de
API** — essa aposta já falhou duas vezes aqui, e a segunda custou uma
rodada inteira com "105 clientes base, 0 com coordenada" na tela, sem um
único erro aparecendo. Para um `.get()`, "campo com outro nome" e "campo
vazio" são a mesma coisa.

As duas plataformas exportam planilha com endereço, e é um dado que a
operação já tem na mão e sabe gerar. Importando, o módulo funciona hoje,
independente de como cada API resolveu chamar o campo nesta versão.

- A origem é detectada **pelo conteúdo**: o relatório da PowerCentral se
  chama `.xls` e por dentro é HTML. Pedir para a pessoa acertar qual é
  qual seria passar para ela um problema que os dois primeiros bytes
  resolvem.
- As colunas são achadas **pelo nome do cabeçalho, nunca pela posição**:
  basta marcar uma coluna a mais na tela de exportação para tudo
  deslocar, e o estrago seria silencioso.
- Cada importação **substitui inteira** a sua própria origem. A planilha
  é o retrato completo daquele lado; misturar com o lote anterior
  deixaria no sistema o endereço de um cliente que já mudou.
- O endereço original fica guardado (`endereco_bruto`). Sem ele, "o
  bairro saiu errado" não teria como ser apurado.

Mesmo assim a API tem prioridade sobre a planilha: a planilha é um
retrato datado, a API é o cadastro de agora.

## 4. Lendo o endereço (`app/domain/endereco.py`, puro)

O cadastro guarda o endereço inteiro num campo de texto só, e quem
preencheu usou a forma que quis. Estes formatos convivem na mesma base:

```
Rua João Monlevade,109,,Jardim Leblon,Belo Horizonte,MG,31540280
R. Plutão, 144 - Santa Lúcia, Belo Horizonte - MG, 30360-450
Rua Miranda Ribeiro, 225, Vila Paris, Belo Horizonte - MG, 30380-660, Brasil
Br 040 Km 688, Ceasa-Pav F Box 40, Kennedy, Contagem-MG
Rua Benjamim Quadros, 255, Paraíso, Belo Horizonte - MG, 30270-130, Brasil - escola
Acrópoluz Soluções em Iluminação
```

**A leitura é de trás para frente.** O começo é imprevisível (logradouro,
nome de empresa, "Br 040 Km 688", vírgula no meio do nome da rua), mas o
fim é disciplinado: país, CEP, UF, cidade, bairro — cada um reconhecível
pela própria forma. Descascando a cauda, o bairro é o que sobra na ponta.

O que **não** pode virar bairro, e por quê:

- **número** ("2350") — é o número da casa de um endereço sem bairro;
- **logradouro** ("Rua N Senora do Perpetuo Socorro") — é a rua de novo;
- **sigla que não é UF** ("Economart Escritório - BH") — "BH" não é
  unidade federativa, e tratá-la como uma transformava o nome da empresa
  em cidade. A validação é contra a lista real das 27, não contra "duas
  letras";
- **país com rabo** ("Brasil - escola") — alguém pendurou o tipo do
  imóvel no fim.

Quem não dá para ler fica sem bairro, de propósito: inventar bairro é
pior que admitir que não sabe, porque manda o técnico para a região
errada e ninguém desconfia.

Um detalhe que custou um bug: o `" - "` **não** é separador no atacado.
Ele aparece dentro de nome de bairro ("Palmares - 4ª Seção (Parque Durval
de Barros)"), e quebrar por ele cortava o bairro ao meio. É tratado só
onde realmente separa.

## 5. O ciclo de preventivas

Uma rodada de visitas é um **ciclo** persistido (`rotas_ciclos` +
`rotas_ciclo_clientes`): o catálogo gerado, mais a marca de quem já foi
visitado e quando.

### Por que o catálogo mora no banco

A primeira versão guardava o resultado no **cookie de sessão**. Com a
base real ele dava **4.746 bytes contra um limite de 4.093** no
navegador: o cookie era descartado em silêncio, e a tela respondia
"nenhum catálogo gerado ainda" logo depois de gerar. Nenhum erro
aparecia, porque do ponto de vista do código a sessão só tinha vindo
vazia — o servidor tinha montado tudo certo.

Guardar no banco é também o que dá memória à rodada: o técnico visita ao
longo de dias, e a marca do que já foi tem que sobreviver a fechar o
navegador, a trocar de máquina e a gerar o catálogo de novo.

### Gerar de novo preserva as visitas

Gerar no meio de uma rodada é rotina — importou planilha nova, entrou
conta nova. A lista de clientes é substituída, mas a marca de cada conta
que continua no catálogo é recolocada. Perder as marcas faria o técnico
repetir locais, que é exatamente o que a marcação existe para evitar.

Pelo mesmo motivo, **gerar não abre um ciclo novo**: se cada geração
abrisse uma rodada, o número do ciclo viraria ruído e a progressão não
significaria nada. Conta que saiu da base sai do ciclo.

### Reiniciar

"Reiniciar ciclo" encerra a rodada (`encerrado_em`) e abre a seguinte com
**os mesmos clientes e nenhuma marca**. Não consulta plataforma nenhuma:
a lista acabou de ser percorrida, e refazer a varredura só para zerar
marcas custaria minutos para não mudar nada.

O ciclo encerrado **fica no banco com as visitas dele**. Zerar por cima
apagaria quando cada local foi atendido, que é o histórico das
preventivas.

### Desmarcar

Marcar errado é fácil e inevitável. Sem o desfazer, o único conserto
seria reiniciar a rodada e perder todas as outras marcas.

### Marcar sem recarregar

A marcação é um `form` de verdade, interceptado por JS. Sem JS a tela
continua funcionando, só recarregando a cada clique; com JS, percorrer
uma lista de cem clientes deixa de exigir cem recarregamentos. Se a
chamada falhar, o formulário é enviado do jeito comum — para a pessoa ver
o erro em vez de achar que marcou.

## 6. Mapa

Um pino por cliente **com coordenada**, cor por bairro, cinza para quem
já foi visitado no ciclo. Marcar na lista repinta o pino na hora, e a
busca filtra os dois juntos — senão o mapa viraria uma segunda versão da
verdade, desatualizada desde o primeiro clique.

**A seção do mapa aparece mesmo sem pino nenhum**, mostrando "0 de 105
com coordenada" e o que fazer. Escondê-la quando dá zero já custou três
rodadas nesta tela: sem o número à vista, "não tem mapa" e "não tem
coordenada" são indistinguíveis. A tabela de importação também ganhou a
coluna **Com coordenada** — zero ali significa planilha enviada antes de
o sistema ler esse campo, que é a causa mais provável de um mapa vazio.

**A coordenada é a mesma história do bairro**: vem da Auvo (API ou
planilha, em campos `Latitude`/`Longitude`) ou da PowerCentral (campo
"Localização da conta", no formato `"lat,long"`), e é reconhecida pela
forma, não pelo nome do campo (`domain/geo.py`). Quem não tem coordenada
**não vira pino**, mas continua na lista e na busca — não aparecer no
mapa não pode sumir com o cliente.

A caixa da região é checada antes de qualquer uso. Na base real, 13 das
104 contas com coordenada no cadastro da PowerCentral apontavam para o
interior de São Paulo: no mapa cada uma dessas é um cliente plantado a
400 km daqui, e o enquadramento inicial abrindo no lugar errado por causa
delas.

### Pinos agrupados

Cem pinos crus em cima de Belo Horizonte viram uma mancha: não dá para
ver quantos clientes há em cada lugar nem clicar num deles. Os pinos
próximos viram uma bolha que **mostra quantos ainda faltam** naquela
região — "o que ainda tenho para fazer aqui" é a pergunta de quem monta a
agenda — e vão abrindo conforme se aproxima.

Bolha verde = tem cliente pendente; **cinza = região inteira visitada**,
recuando junto com os pinos já visitados. Verde nos dois casos seria pior
que não ter cor: só o número mudaria de significado (pendentes x total),
sem nenhuma pista de qual é qual.

Leaflet **1.9.4** e **Leaflet.markercluster 1.5.3** vendorizados em
`static/vendor/leaflet/` (BSD-2 e MIT), não CDN: o site roda na rede
interna e precisa abrir sem depender de CDN. Só os tiles vêm do
OpenStreetMap — sem internet o mapa fica cinza, mas a página e as tabelas
continuam inteiras. As bibliotecas só são carregadas quando há pino para
desenhar; sem coordenada nenhuma, seriam 180 KB de peso para desenhar
zero.

Os pontos chegam ao JS por `data-attribute`, não por uma chamada à API: a
tela já recebeu o catálogo renderizado.

## 7. Busca

Filtra por cliente, conta, bairro ou cidade, sem acento e sem caixa, na
lista **e** no mapa. Bairro que fica sem resultado é escondido; bairro
com resultado é aberto — procurar e ter que abrir cada região à mão seria
inútil.

É filtro no navegador, não consulta: o catálogo inteiro já está na tela,
e uma ida ao servidor por tecla digitada seria lentidão sem ganho.

## 8. Corrigir o bairro à mão

O bairro lido do endereço acerta em 93% dos cadastros preenchidos. Para o
resto — endereço sem bairro escrito ("Shopping Cidade"), bairro errado,
formato que o leitor não interpreta — existe o botão **Bairro** em cada
linha.

- A correção é gravada **fora do ciclo** (`rotas_bairros_manuais`), de
  propósito: ela tem que sobreviver a gerar o catálogo de novo e a
  reiniciar a rodada. Se morasse no ciclo, a próxima geração desfaria o
  trabalho de quem corrigiu, em silêncio.
- **Vence todas as outras fontes**, pelo mesmo motivo que o de-para com
  status OK vence o casamento por nome: alguém olhou e decidiu.
- O campo **sugere os bairros que já existem** na base. Digitar "Padre
  Eustaquio" onde o resto tem "Padre Eustáquio" criaria duas regiões para
  o mesmo lugar.
- **Bairro em branco apaga a correção** — é como se volta a confiar na
  leitura automática depois de arrumar o cadastro na origem.
- A tela mostra a correção na hora, no ciclo aberto. Sem isso, a pessoa
  corrigiria e a tela continuaria igual até a próxima geração, que leva
  minutos e ninguém vai rodar por uma linha.

## 9. Quem não tem bairro não some

Vai para uma região `(sem bairro) — Cidade`, no fim da lista. Some seria
pior: ninguém procura o que não aparece. Essa é a fila de trabalho do
cadastro, e sai numa aba própria do Excel.

## 10. Resiliência

- **Auvo fora do ar não cancela nada**: sobram a planilha importada e a
  PowerCentral. Entregar parte é melhor que não entregar nada — e o
  resumo mostra de onde veio cada endereço e avisa o que faltou.
- **PowerCentral fora** aborta com erro próprio: sem a lista de contas
  não existe nada para catalogar.
- O Excel sai **exatamente** igual ao que está na tela, porque os dois
  leem o mesmo ciclo gravado, e traz a coluna de quando cada cliente foi
  visitado.
- Importar planilha **não** mexe no ciclo: descartá-lo jogaria fora as
  visitas já marcadas. O catálogo fica como está até alguém gerar de
  novo, e a mensagem da importação diz isso.

## 11. Validação com a base real

Pior caso simulado: a API da PowerCentral devolvendo **só conta e nome**,
a Auvo fora do ar, tudo vindo das duas planilhas importadas.

| | |
|---|---|
| Clientes no export da Auvo | 579 (473 com endereço útil) |
| Contas no relatório da PowerCentral | 148 (147 com cidade) |
| Clientes base | **106** |
| Com bairro | **76** |
| Só com a cidade | **30** |
| Sem região nenhuma | **0** |
| Bairros distintos | **59** |
| Com coordenada (pino no mapa) | **97** |
| Sem pino | **9** |

Leitura do endereço isolada, sobre os 488 endereços preenchidos da Auvo:
**93% com bairro legível**. Os 7% restantes são endereços que realmente
não têm bairro escrito ("Acrópoluz Soluções em Iluminação", "Shopping
Cidade").

Da coluna "Rua" da PowerCentral sai quase nada — de 148 contas, uma tinha
bairro legível. Por isso a PowerCentral entra como fonte de **cidade**, e
a Auvo como fonte de bairro.

## 12. Conferir contra as plataformas de verdade

```
.venv\Scripts\python.exe scripts\debug_rotas.py
```

Imprime os **nomes de campo que cada plataforma realmente devolve**, o
que o detector de endereço enxerga em cada registro, quantos clientes
sobrevivem a cada etapa e a fila do cadastro. É só leitura. Quando um
número da tela não fizer sentido, é por aqui que se descobre em qual
etapa ele se perde, em vez de adivinhar.
