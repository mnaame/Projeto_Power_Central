# Módulo BI: Eficácia do Técnico (ordens Auvo × disparos)

Extensão de [`ARQUITETURA.md`](ARQUITETURA.md), [`RELATORIOS.md`](RELATORIOS.md),
[`CHAMADOS_AUVO.md`](CHAMADOS_AUVO.md) e [`RELATORIO_TECNICO.md`](RELATORIO_TECNICO.md)
— mesmas camadas, mesma disciplina. Especificação de origem: complemento
"BI: Eficácia do Técnico". Este documento registra o que foi confirmado
contra o código real e os pontos que **ainda precisam de validação** com
dado de produção antes de confiar no número (§6).

## 1. A pergunta e a unidade de análise

"O atendimento do técnico reduziu os disparos do cliente?" Cada ordem
**concluída** na Auvo numa loja com de-para **OK** vira uma intervenção:
conta-se os disparos **válidos** (mesma régua de `domain/disparos.py`) por
dia numa janela ANTES `[marco-15d, marco)` e DEPOIS `(marco, marco+15d]`
do marco (data de conclusão), normalizado por dia corrido da janela, e
classifica-se a variação. Ver §2 do complemento original para a régua
completa (limiares, `SEM_BASE`, `PARCIAL`, `ATRIBUICAO_COMPARTILHADA`).

## 2. Realidade dos dados — confirmado

Disparo não fica persistido (só `CycleAccount`/falha TST é gravado pelo
coletor); BUR é sempre buscado ao vivo via `SoftGuardClient.buscar_historico`.
Portanto o recálculo faz **uma única** chamada paginada cobrindo
`[menor data de tarefa concluída − janela, maior data de tarefa concluída +
janela]` (capado em hoje), com os códigos `CODIGO_DISPARO + CODIGOS_ARME +
CODIGOS_DESARME` de `domain/disparos.py` (mesma tupla que
`report_service.gerar_disparos` já usa) — e separa por conta em memória.
Resultado grava em `BiRun`/`BiIntervencao`; o dashboard só lê daí.

## 3. Onde muda o plano original (depois de ler o código)

- **De-para reverso reaproveitado, não duplicado.** `tecnico_service.py`
  já tinha `_conta_por_id_auvo(id_auvo)` (só status `OK`, desempate
  determinístico por `conta_power`) — promovido para público
  (`tecnico_service.conta_por_id_auvo`) e importado direto pelo
  `bi_service.py`. Sem reescrever a régua numa segunda cópia.
- **`avaliar_disparos_da_conta` roda uma vez por conta, no histórico
  INTEIRO do período** (não uma vez por janela ANTES e outra vez por
  janela DEPOIS). Motivo: a função usa arme/desarme ao redor de cada BUR
  para decidir "rotina de entrada/saída"/"ciclo curto"; cortar o histórico
  exatamente no marco perderia o contexto de um BUR perto da borda. A
  lista de `DisparoAvaliado` (já com `.valido`/`.quando`) sai uma vez;
  cada intervenção da mesma conta só filtra esse resultado pelo intervalo
  de tempo — reaproveitando entre intervenções da mesma conta quando o
  técnico visitou mais de uma vez no período.
- **Sem tabela própria para "sem vínculo".** Vira só um contador no
  resumo do run (`BiRun.resumo["sem_vinculo"]`) — não precisa de uma
  linha por tarefa sem de-para, só o total visível na tela.
- **Agregações (ranking por técnico, clientes crônicos, série de
  tendência) não são persistidas** — `BiRun`/`BiIntervencao` já são o
  cache caro (a chamada de rede); somar/agrupar isso em Python a cada
  carregamento de tela é rápido e evita mais uma camada de cache para
  invalidar. Funções puras em `domain/bi.py` recebem a lista de
  intervenções do run e devolvem `ResumoTecnico`/`ClienteCronico`.
- **Gráficos: SVG renderizado no servidor**, não Chart.js. O dashboard
  (`app/web/dashboard/routes.py:_serie_grafico` +
  `templates/dashboard/_conteudo.html`) já tem exatamente esse padrão —
  pontos calculados em Python, `<svg><polyline></svg>` no template, CSS
  de `app.css` (`chart-line`/`chart-grid`/`chart-point`). Reaproveitado
  para "antes×depois" (barras) e "tendência" (linha com marcos).
- **Exportação estende `report_xlsx.py`** (`_montar_aba` já é genérico) —
  novas colunas/funções para intervenções e clientes crônicos, mesmo
  estilo (cabeçalho verde, `freeze_panes`, `auto_filter`) das outras
  planilhas.
- **"Tendência" não é uma série semanal contínua.** O plano original
  pedia "disparos/semana com marcos das visitas"; como só
  `BiIntervencao` fica persistido (os eventos crus do `buscar_historico`
  são descartados ao fim do recálculo — persistir tudo derrotaria o
  propósito do cache), uma série semanal de verdade exigiria re-buscar
  ou guardar dado bem mais granular. A linha mostra, em ordem
  cronológica, o `depois_por_dia` de CADA intervenção — cada ponto já É
  um marco de visita, então "marcos das visitas" está coberto sem
  precisar de uma série separada.
- **Janela e limiares viraram override opcional por recálculo**
  (`bi_service.recalcular(janela_dias=..., limiar_melhora_pct=...,
  limiar_piora_pct=...)`, todos `None` por padrão = usa o que está em
  `settings_service`) — o complemento pede isso na seção "avançado" dos
  filtros da tela.
- **Drilldown**: `tecnico.index` ganhou `?tecnico=` e `?data_agenda=`
  opcionais para pré-preencher os filtros (mudança de duas linhas em
  `app/web/tecnico/routes.py`) — clicar numa intervenção do BI leva pro
  Técnico já com o nome do técnico e a data da visita prontos pra
  "Puxar agenda do dia".

## 4. Camadas

### 4.1 `app/domain/bi.py` (novo, lógica pura)

- Dataclasses (todos os campos obrigatórios, sem default — mesmo estilo de
  `ClienteComDisparos`/`DisparoAvaliado` em `domain/disparos.py`):
  `Classificacao` (só os números), `Intervencao` (identidade + números),
  `ResumoTecnico`, `ClienteCronico`.
- `classificar_janela(avaliados, *, marco, agora, janela_dias,
  limiar_melhora_pct, limiar_piora_pct) -> Classificacao`: conta
  `d.valido and quando` dentro de cada janela, normaliza por dia
  (`dias_depois` real quando a janela ainda não fechou → `parcial=True`),
  `SEM_BASE` quando `antes_por_dia == 0`. Quem chama (`bi_service.py`)
  combina o resultado com os campos de identidade (conta, loja, técnico,
  task id) para montar o `Intervencao` final.
- `tem_atribuicao_compartilhada(marcos_da_conta, *, marco, janela_dias)`:
  outro marco da mesma conta caindo dentro do DEPOIS desta intervenção.
- `tarefa_concluida(tarefa)` / `data_conclusao(tarefa)`: mesmo estilo
  defensivo de `domain/tecnico.py` — **ver §6, campo de data ainda não
  validado contra produção**. `tarefa_concluida` reusa o critério já
  confirmado (`finished is True` ou `taskStatus == 5`, mesmo valor de
  `auvo_service.TASK_STATUS_FECHADOS`, mantido como constante própria
  porque `domain/` não importa de `services/`).
- `resumo_por_tecnico(intervencoes, *, amostra_minima) -> list[ResumoTecnico]`
  e `clientes_cronicos(intervencoes, *, visitas_para_cronico) ->
  list[ClienteCronico]` — agregações puras sobre uma lista de
  `Intervencao` (vem do banco ou de memória, tanto faz para a função).

### 4.2 `app/models/bi.py` (novo) + migration

- **`bi_runs`**: `id`, `criado_em`, `criado_por_user_id`, `periodo_desde`,
  `periodo_hasta`, `janela_dias`, `limiar_melhora_pct`, `limiar_piora_pct`,
  `tecnico_filtro`, `status` (`running`/`success`/`error`),
  `erro_mensagem`, `resumo` (JSON — contadores: total, por classificação,
  sem_vinculo, disparos_evitados_estimados). Mesma forma de
  `ReportRun.extra_counts`/`TecnicoLote`.
- **`bi_intervencoes`**: `id`, `run_id` (FK), `task_id_auvo`,
  `conta_power`, `id_auvo_cliente`, `nome_loja`, `tecnico_nome`, `marco`
  (TZDateTime), `antes_por_dia`, `depois_por_dia`, `variacao_pct`
  (nullable — `SEM_BASE` não divide), `classificacao`, `parcial`,
  `atribuicao_compartilhada`, `dias_depois`.

### 4.3 `app/services/bi_service.py` (novo)

- `recalcular(*, config, periodo_desde, periodo_hasta, tecnico, user_id,
  auvo_client=None, softguard_client=None) -> BiRun`: busca tarefas
  concluídas (`AuvoClient.listar_tarefas`, filtra por
  `tarefa_concluida`+`tecnico_corresponde`), calcula o intervalo de busca
  do histórico a partir das datas de conclusão, faz **uma** chamada
  `buscar_historico`, agrupa por conta (reaproveita
  `disparos.agrupar_por_conta`, casado por `cue_ncuenta` normalizado —
  não por `rec_iidcuenta`, que é o id interno do disparo e não bate com
  `conta_power` do de-para), roda `avaliar_disparos_da_conta` uma vez por
  conta, monta as intervenções (com atribuição compartilhada calculada
  depois de ter todos os marcos da conta) e grava `BiRun`+`BiIntervencao`.
  Falha isolada por conta nunca derruba o run inteiro. Lock por
  execução única (mesmo padrão de `_executar_com_lock`/
  `tentar_iniciar_execucao`).
- `ultimo_run()`, `carregar_run(id)`.
- Wrappers finos sobre `domain.bi.resumo_por_tecnico`/`clientes_cronicos`
  para a tela não importar `domain/` direto.

### 4.4 `app/web/bi/` (blueprint `bi`, prefixo `/bi`)

Rotas: `index` (GET, lê o último run ou o `run_id` da query), `recalcular`
(POST), `run_detalhe/<id>`, `exportar/<id>/<tabela>`, `configuracao` +
`salvar_configuracao` (admin). Link na sidebar depois de "Relatório do
Técnico". Drilldown de cliente aponta para `tecnico.index` (mesma conta),
não duplica export de histórico.

### 4.5 `app/domain/bi_painel.py` + `app/domain/graficos.py` (a tela)

Camadas puras entre o cálculo e o template. `bi_painel` decide **o que a
tela diz** (frase, funil, lojas por resultado, série semanal);
`graficos` decide **onde cada barra fica**. Nenhum número novo nasce
aqui — e a geometria sai do template para poder ser testada (gráfico
errado não dá exceção, dá uma barra do tamanho errado em que o leitor
acredita).

## 4.6 O painel confundia — e por quê

Os três números do topo pareciam falar da mesma coisa e tinham
**denominadores diferentes**: "133 intervenções", "40% que melhorou" e
"506,4 disparos evitados". O 40% era **4 de 10** — só dez visitas tinham
base de comparação. Número grande sobre amostra pequena não é detalhe de
apresentação: é o número ser lido como se valesse para as 133. Além
disso, com **um técnico só** na operação, o gráfico "por técnico" era uma
barrinha e o "ranking de técnicos" era uma linha.

As decisões que resolveram, todas com teste de mutação:

1. **Uma frase em português no topo**, gerada dos mesmos números dos
   cartões: _"No período, Alfredo fez 133 manutenções. Nas 10 lojas que
   dava para comparar, os disparos caíram em 4, pioraram em 2 e ficaram
   iguais em 4. Estima-se ~506 disparos a menos. 6 lojas seguem
   crônicas."_ Se a frase e um cartão discordarem, é bug, não
   arredondamento.
2. **Percentual nunca anda sozinho.** "4 de 10" grande, "40%" pequeno ao
   lado. E um bloco "De onde vêm os números" com a conta inteira —
   ordens concluídas → sem vínculo → sem base → com base → lojas →
   melhoraram. É o que faz "133" e "4 de 10" conviverem sem parecer
   contradição.
3. **A unidade da manchete é a LOJA, não a visita.** Uma loja visitada
   cinco vezes contava cinco vezes em "melhorou" — e a loja mais visitada
   é justamente a mais problemática, então ela dominava a estatística. O
   funil faz a ponte entre as duas unidades às claras.
4. **Visita sem base não entra na média da loja.** Incluí-la como
   "antes = 0" puxaria o antes para baixo e faria uma loja que **piorou**
   aparecer como melhorada. É o erro mais caro do módulo e tem teste
   próprio.
5. **O "depois" da loja é ponderado pelos dias medidos.** Uma visita de
   ontem tem 1 dia de evidência e uma de um mês atrás tem 15; média
   simples deixaria a mais recente — a com menos evidência — decidir a
   classificação.
6. **Sem falsa precisão.** "506,4" vira "~506", com a frase "estimativa
   de quantos disparos a menos ocorreram depois das visitas".
7. **Estado vazio é tratado.** Sem lojas comparáveis, o cartão diz
   "ainda sem lojas comparáveis no período" em vez de um "0%" seco, que
   leria como fracasso do técnico.
8. **O cartão de crônicas é clicável** e leva à lista — é o número mais
   acionável do painel.
9. **Jargão com "?"**: sem vínculo, sem base, estável, crônico e
   "disparos evitados" têm uma frase de explicação (`GLOSSARIO`).

### 4.7 Regras de gráfico

- **Uma escala por gráfico.** Nunca dois eixos Y.
- **Forma segue função.** Saíram o "antes × depois por técnico" (uma
  barra) e o "ranking" (uma linha); entraram o **antes × depois geral**
  (duas barras) e a **lista de lojas por resultado**, ordenável, que é
  onde se age. O técnico virou um cartão simples.
- **Tendência por semana, em barras.** Não existe série diária de
  disparos persistida — só o que foi medido em volta de cada visita.
  133 pontos numa linha de 660px viram borrão, e uma linha ligando
  visitas esparsas sugere uma continuidade que o dado não tem. Semana sem
  visita aparece **sem barra**: barra zerada diria "zero disparos", que é
  diferente de "ninguém foi medido". A contagem de visitas da semana sai
  no hover.
- **Hover com mira e dica** (data, valor, nº de visitas), com alvo do
  tamanho da faixa e não da barra — acertar uma coluna de 8px no celular
  é impossível. É melhoria, não o único caminho: o `<title>` nativo
  continua lá e todo número está na tabela abaixo.
- **Eixo justo.** `eixo()` testa 4, 5 e 3 divisões e fica com o teto mais
  apertado. Com divisão fixa em 4, um máximo de 1,20 fechava em 2,00 e
  jogava fora 40% da altura — foi o que a primeira renderização mostrou.
- **Marcas finas**: coluna de no máximo 24px, ponta arredondada de 4px e
  **base quadrada** (`rx` arredondaria os quatro cantos e a barra
  descolaria do eixo), grade e eixo em hairline **sólido**.
- **Cor por função, nunca por enfeite.** `--chart-neutro` (antes),
  `--chart-melhora`, `--chart-piora`, `--chart-serie` (medição sem
  julgamento). Status nunca vira "série 3" e **sempre** sai com ícone +
  palavra. Texto — valores, eixos, rótulos — usa tom de tinta, nunca a
  cor da série.

### 4.8 As cores dos gráficos nos quatro temas

Os `--chart-*` são desenhados tema a tema, não o mesmo valor invertido:
um verde que lê bem no branco some no #000, e o cinza quente do sépia
encosta no verde dele.

Conferidos com o validador de paleta do guia de dataviz, **par a par,
contra a superfície de cada tema** — só os pares que dividem o mesmo
gráfico (neutro × melhora, neutro × piora). Dois achados reais:

- No **tema claro**, o cinza esverdeado natural da paleta ficava a
  ΔE 12,1 do verde institucional (piso de visão normal é 15) — e essas
  duas barras ficam lado a lado. O cinza do gráfico virou **frio**
  (`#7a7f85`, ΔE 15,5).
- No **sépia**, o cinza quente encostava no verde (12,2) e no âmbar
  (13,4); virou um cinza mais escuro (`#7d7670`, ΔE 20,1 / 21,5).

Verde × âmbar nunca dividem um gráfico (a barra "depois" é um ou outro) e,
na tabela, andam com ícone + rótulo.

## 5. Settings novas (`bi_*`)

`bi_janela_dias` (15), `bi_limiar_melhora` (20), `bi_limiar_piora` (20),
`bi_tipos_intervencao` (vazio = todos), `bi_visitas_para_cronico` (3),
`bi_periodo_padrao_dias` (90), `bi_amostra_minima_tecnico` (5).

## 5.1 Correções pós-entrega (visto em produção)

- **`page_size` do `buscar_historico`** subiu de 100 (padrão do client)
  para 2000 (`PAGE_SIZE_HISTORICO`) — com a base de contas real da
  operação, 90 dias de TODAS as contas em blocos de 100 virava milhares
  de idas e voltas HTTP sequenciais (um recálculo passou de 30 min sem
  terminar). `"Mostrar": 5000` já é enviado em toda chamada de
  `buscar_historico` (herdado do motor validado), então o portal já é
  dimensionado para páginas desse tamanho.
- **Commit cedo do `BiRun`**: antes, o registro "running" só ia para o
  banco (commit de verdade, não só flush) no fim do recálculo inteiro —
  com a parte de rede levando minutos, isso segurava o lock de escrita
  do SQLite pelo tempo todo e derrubava o ciclo automático do coletor
  (a cada 5 min) com `sqlite3.OperationalError: database is locked`
  (visto em produção, no log do coletor). Agora o `BiRun` é commitado
  assim que criado (status `running`), soltando o lock antes de começar
  a parte lenta; só a atualização final (rápida, sem rede) segura o
  lock de novo. A tela ganhou um aviso para quando alguém abre `/bi`
  enquanto um recálculo de outra pessoa ainda está `running`.
- **Timeout do client subiu para 120s** (`TIMEOUT_HISTORICO_SEGUNDOS`) —
  o padrão de 15s não é suficiente para uma busca desse tamanho.

## 6. Precisa de validação antes de confiar no número

`tarefa_concluida` reusa o critério **já confirmado** contra a tarefa real
77330829 (`finished`/`taskStatus`). O **campo da data de conclusão não foi
confirmado** — só se sabe que a tarefa carrega um `checkOut` booleano, não
uma data. `data_conclusao` tenta, em ordem, candidatos plausíveis
(`checkOutDatetime`, `checkOutDate`, `finishedDate`, `modifiedDate`,
`updatedDate`) e cai para `taskDate` (data agendada, não a de conclusão —
aproximação de último caso) se nada bater; nunca quebra, só devolve vazio.
**Antes de usar o ranking para decisão**, validar com o método de sempre:
rodar `python scripts\debug_bi_data_conclusao.py <id>` (novo, RT4) numa
tarefa concluída de verdade — mostra o JSON completo, quais candidatos
existem e qual data `data_conclusao()` escolheria — conferir contra o que
se sabe daquela visita, e ajustar `_CAMPOS_DATA_CONCLUSAO` em
`app/domain/bi.py` se precisar (mesmo processo que validou
`finished`/`taskStatus` e os campos de `domain/tecnico.py`). Isso ainda
**não foi feito** — fica documentado em `docs/OPERACAO.md` §5.2.4 como
passo obrigatório antes de usar o BI para avaliar técnicos.

## 7. Fases

| Fase | Entrega | Prova |
|---|---|---|
| **BI1** ✅ | `domain/bi.py` + modelos + migration + settings | Unit: janela/classificação (melhorou/piorou/estável/sem-base/parcial), atribuição compartilhada, `tarefa_concluida`/`data_conclusao` defensivos |
| **BI2** ✅ | `bi_service.py` completo | Integração: recálculo fim-a-fim com fakes, falha isolada por conta, agregações |
| **BI3** ✅ | Aba web (filtros, KPIs, gráficos SVG, tabelas exportáveis, drilldown) | Integração web + screenshots claro/escuro (Playwright) |
| **BI4** ✅ | Config admin + docs + script de validação do campo de data | Suíte completa verde |

Módulo concluído do lado do código. O único item que depende do usuário
(não dá para validar sem acesso à Auvo de produção) é a validação do
campo de data de conclusão — ver §6 e `docs/OPERACAO.md` §5.2.4.

O que NUNCA entra no repositório: credenciais (já cobertas), nomes reais
de técnicos/clientes além do que já está nas configs.
