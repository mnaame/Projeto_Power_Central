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

## 6. Quem não tem bairro não some

Vai para uma região `(sem bairro) — Cidade`, no fim da lista. Some seria
pior: ninguém procura o que não aparece. Essa é a fila de trabalho do
cadastro, e sai numa aba própria do Excel.

## 7. Resiliência

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

## 8. Validação com a base real (13/10)

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

Leitura do endereço isolada, sobre os 488 endereços preenchidos da Auvo:
**93% com bairro legível**. Os 7% restantes são endereços que realmente
não têm bairro escrito ("Acrópoluz Soluções em Iluminação", "Shopping
Cidade").

Da coluna "Rua" da PowerCentral sai quase nada — de 148 contas, uma tinha
bairro legível. Por isso a PowerCentral entra como fonte de **cidade**, e
a Auvo como fonte de bairro.

## 9. Conferir contra as plataformas de verdade

```
.venv\Scripts\python.exe scripts\debug_rotas.py
```

Imprime os **nomes de campo que cada plataforma realmente devolve**, o
que o detector de endereço enxerga em cada registro, quantos clientes
sobrevivem a cada etapa e a fila do cadastro. É só leitura. Quando um
número da tela não fizer sentido, é por aqui que se descobre em qual
etapa ele se perde, em vez de adivinhar.
