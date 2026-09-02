# Módulo: Bot do Técnico no Telegram (relatório + zoneamento sob demanda)

Extensão de [`ARQUITETURA.md`](ARQUITETURA.md) — mesmas camadas
(domain/integrations/services/web), regras puras testáveis sem rede, tudo
auditado. Especificação de origem: complemento "Bot do Técnico no
Telegram". Objetivo: parar de responder técnico na mão — ele pede pelo
Telegram e o bot entrega na hora.

## 1. A mudança de arquitetura: o Telegram passa a ESCUTAR

Até aqui o `TelegramClient` só **empurrava** (alertas do coletor,
watchdog, relatório periódico). Este módulo acrescenta o outro lado:
`getUpdates` em **long polling**, num worker de fundo.

**Long polling, não webhook** — decisão consciente: o site é local, sem
URL pública com HTTPS. Webhook exigiria expor o servidor na internet;
polling não exige nada. (Se um dia o site for publicado com HTTPS, webhook
vira uma evolução natural — o resto do módulo não muda.)

A thread sobe junto com o scheduler (`app/scheduler.py`) e checa
`bot_ativado` **a cada volta**, não só na subida: ligar/desligar na tela
vale na hora, sem reiniciar o serviço.

## 2. Postura de segurança (por que este módulo é diferente)

O que ele entrega é dado sensível: o **zoneamento é o mapa de sensores do
cliente** (onde tem sensor, o que cada um dispara) e o histórico expõe a
rotina dele — a que horas arma, a que horas desarma.

- **Lista fechada por ID de usuário do Telegram** (`bot_tecnicos_ids`).
  Padrão vazio = ninguém é atendido; autorizar é ato explícito do admin.
- **Autoriza-se por QUEM ENVIOU (`from.id`), nunca pelo grupo.** Estar num
  grupo autorizado não basta — qualquer um pode ser adicionado a um grupo.
  Ainda assim, a recomendação operacional é um grupo dedicado de técnicos.
- **Toda tentativa vai para a auditoria**, autorizada ou não
  (`bot_zona_pedido`, `bot_relatorio_pedido`, `bot_pedido_negado`), com
  quem/qual conta/quando — e **sem o conteúdo** do zoneamento ou do
  histórico no `details`.
- **Cooldown por usuário** (`bot_cooldown_segundos`, padrão 10): um
  comando repetido não vira dezenas de consultas pesadas no portal.
- Toda resposta leva o aviso de **uso interno** (não repassar ao cliente).

## 3. Camadas

### 3.1 `app/domain/bot_comandos.py` (puro)

- `interpretar(texto) -> Comando`: parsing tolerante — aceita `/zona 95`,
  `/ZONA 95` e `/zona@MeuBot 95` (o Telegram acrescenta o `@bot` em grupo).
  Comando desconhecido ou texto solto devolve nome vazio: **o bot não
  responde conversa de grupo**, só comando que ele conhece.
- `separar_conta_e_dias(argumentos)`: `/relatorio <conta> [dias]`. O último
  argumento só vira "dias" se for número **e** houver mais de um argumento
  — assim `/relatorio 9516` continua sendo a conta 9516.
- `resolver_conta(termo, contas)`: aceita número (`95`, `0095` — mesma
  normalização de conta do resto do sistema) ou parte do nome (sem acento,
  sem caixa). **Ambiguidade nunca vira chute**: com mais de um cliente
  casando, devolve `RESOLUCAO_AMBIGUA` com as candidatas e o bot pede o
  número. Mandar o zoneamento da loja errada é vazar o mapa de segurança de
  um cliente para outro. Nome idêntico resolve a ambiguidade ("VILLEFORT
  HM" não fica preso porque existe "VILLEFORT HM DEPOSITO"). Quando o
  termo cai na conta **mãe** de um local com setores separados, devolve
  `RESOLUCAO_PARTICOES` com a família (§4.2).

### 3.2 `app/domain/zoneamento.py` (puro)

- `zonas_da_resposta(linhas)`: lê `zon_ccodigo` (vem preenchido com espaços
  no portal → `.strip()`), `zon_cdescripcion` e `zon_cAlarmaAGenerar`.
  **Preserva a ordem recebida** — a consulta já pede `orderCodigo ASC`, que
  é a ordem da tela (numéricas primeiro, SP1/SP2 depois); reordenar aqui
  mudaria o que o técnico está acostumado a ver.
- `formatar_zoneamento(...)`: cabeçalho com conta/cliente/total e uma linha
  por zona, com as colunas alinhadas.

### 3.3 `app/integrations/softguard_client.py`

`listar_zonas(cue_iid)` — `GET /Rest/Zona/` no padrão do `_buscar_paginado`
(login por cookie, envelope `rows`, retry). O filtro é o da própria tela:

```json
[{"property":"zon_ccodigo:LIKENOT","value":"PAR"},
 {"property":"zon_ccodigo:ISNOTNULLOREMPTYTRIM","value":""},
 {"property":"zon_iidcuenta","value": <cue_iid>}]
```

Os dois primeiros tiram as partições e as zonas vazias — juntos dão
exatamente o "zoneamento completo". `cue_iid` é o **mesmo** id interno já
usado no export do histórico e no `CuentaByDealer`; aqui ele entra como
`zon_iidcuenta`. Ordenação `orderCodigo ASC`, `limit=400` (como a tela).

### 3.4 `app/integrations/telegram_client.py`

- `buscar_updates(offset, timeout)` — o long polling. O timeout do HTTP é
  maior que o do polling, senão a requisição morreria antes de a espera
  terminar.
- `enviar_documento(...)` — `sendDocument` para o arquivo do relatório
  (limite da legenda é 1024, bem menor que o da mensagem).
- `enviar_mensagem(..., chat_id=...)` — o bot responde **no chat de onde
  veio o comando**; sem `chat_id` continua indo para o chat configurado,
  então os alertas do coletor não mudam.

### 3.5 `app/services/telegram_bot_service.py`

Orquestra: loop, autorização, cooldown, despacho e auditoria.

- `_SessaoSoftGuard`: mantém o `SoftGuardClient` **logado entre comandos**
  (relogar a cada pedido é lento e castiga o portal) e guarda o mapa de
  contas em cache de 30 min (é a lista inteira do dealer, consulta cara).
  **Com prazo** — ver §3.6.
- `processar_update(...)`: um update. Erro de negócio vira resposta ao
  técnico; `SoftGuardAuthError` derruba o cache da sessão e pede para
  repetir.
- `_uma_volta(...)`: uma iteração do loop. **O offset avança ANTES de
  tratar** o update — um comando que quebre de um jeito não previsto não
  pode ser reprocessado em loop infinito a cada volta.
- **Ao (re)ligar, a fila pendente é descartada sem executar**: o Telegram
  guarda updates por ~24h, e sem isso comandos parados há horas
  disparariam todos de uma vez no instante em que alguém liga o bot.
- Exceção tratando um update é registrada e o loop segue (mesma
  resiliência do coletor).

### 3.6 A sessão reaproveitada precisa de prazo (bug real)

Reaproveitar o login entre comandos é pedido do complemento — e foi o que
quebrou o bot em produção no primeiro dia. O `SoftGuardClient` faz login
**uma vez** (`_logged_in` só é setado na subida) e nunca reautentica:
`_request` repete a chamada até 3 vezes, mas sempre com a mesma sessão. No
resto do sistema isso nunca apareceu porque cada operação cria um client
novo (`report_service`, `tecnico_service`, `bi_service`).

Quando o token venceu, o portal passou a responder **500 — não 401**, em
`/Rest/Zona/` e no export. Como o client ficava em cache, a sessão morta
ficava morta para sempre: o bot respondia "a PowerCentral não respondeu" a
tudo até alguém reiniciar o serviço. No log de auditoria dava para ver o
corte exato: sucesso às 09:42, 500 em tudo a partir das 09:53.

Duas defesas, porque uma só não basta:

1. **Prazo de sessão** (`VALIDADE_SESSAO`, 20 min): o client é descartado
   por idade, então no caminho normal a sessão nunca chega a vencer.
2. **`_executar_renovando_sessao`**: se ainda assim o portal falhar, a
   sessão é jogada fora e o comando é tentado **uma vez** com login novo.
   Uma só — se o portal estiver fora de verdade, o técnico recebe o aviso
   em vez de o bot ficar num laço.

Repetir o comando é seguro porque nada é enviado ao técnico antes das
chamadas ao portal: as respostas de "não achei"/"qual?" retornam sem
exceção, e o documento/zoneamento só sai depois que o portal respondeu.

A auditoria também passou a guardar **o que foi pedido** nas falhas —
antes, um erro do portal não dizia sequer qual conta o técnico tinha
pedido.

## 4. Comandos

| Comando | O que faz |
|---|---|
| `/relatorio <conta> [dias]` | Histórico de eventos em **dois arquivos**: `.xls` nativo (cores da plataforma, abre no PC) e `.pdf` (abre no celular sem app de planilha) + resumo na legenda do primeiro |
| `/zona <conta ou nome>` | Zoneamento completo, em texto monoespaçado |
| `/clientes [filtro]` | Lista a base com as partições; filtro por nome ou número |
| `/ajuda` | Referência completa: todos os comandos com exemplo, como informar a conta, como funcionam as partições e o prazo do cooldown. Lê os números da configuração (dias padrão, cooldown) em vez de escrevê-los fixos — senão a ajuda vira mentira quando a config muda. Não consome cooldown |

**Partições** (§4.2): cada setor (tesouraria, depósito) é uma conta com
número próprio, então o número já basta. Pedir a conta **mãe** faz o bot
listar os setores e perguntar.

### 4.1 O total de eventos sai do arquivo, não de `buscar_historico`

A primeira versão contava os eventos com `buscar_historico` — **errado, e
quebrou no primeiro teste real** ("A PowerCentral não respondeu"). Motivo:
`buscar_historico` **não tem filtro de conta**. Chamá-lo aqui puxava o
histórico da base inteira (todas as contas do dealer, em blocos de 100)
só para contar os eventos de uma loja: lento a ponto de estourar, e o
número que sairia seria o da base toda, não o da conta pedida.

Agora o comando faz **uma** chamada — o próprio export, que já é filtrado
pela conta — e conta as linhas do arquivo com
`dom_tecnico.contar_eventos_do_export`, que reusa as mesmas expressões de
leitura do HTML já validadas em `montar_workbook_colorido`.

Quando o export é **recusado por permissão** do usuário de integração, o
bot diz isso em vez de "tente de novo": repetir não resolve, e o técnico
precisa saber que o caminho é avisar o escritório.

### 4.2 Partições

**Validado em produção** com `scripts/debug_particoes.py` — e o resultado
derrubou a suposição inicial deste módulo, que era ler o filtro
`cue_nparticion = 0` como "número da partição". O que a base real mostra:

- **cada partição é uma conta própria**, com o seu `cue_ncuenta` e o seu
  `cue_iid`. A tesouraria da VILLEFORT TROPICAL (conta 0004) é a conta
  **0005**, "VILLEFORT ATACADISTA TROPICAL - TESOURARIA";
- **`cue_nparticion` não é o número da partição** — é o `cue_iid` da conta
  MÃE (0 quando a conta não é partição de ninguém). É por isso que o
  filtro `cue_nparticion = 0` do resto do sistema devolve exatamente as
  contas principais;
- o vínculo legível com a mãe vem em `madre_ncuenta` / `madre_cnombre`.

Consequência boa: **não existe sintaxe especial**. Como a partição é conta
de verdade, `/zona 5` já entrega a tesouraria. A primeira versão inventou
um `95/2` que não corresponde a nada na base — foi removido.

Quando perguntar, e quando não (corrigido depois de quebrar em produção):

- **Número explícito resolve direto.** `/relatorio 154` entrega a 154. A
  primeira versão perguntava aqui também — e como a conta mãe **sempre**
  tem partição, `/relatorio 154` caía na mesma pergunta para sempre: não
  havia caminho nenhum para o relatório da conta principal.
- **Busca por nome pergunta**, se o local tiver setores. Aí o técnico pode
  nem saber que existe uma tesouraria separada, e entregar o setor errado
  é entregar dado errado — mesma disciplina do nome ambíguo.

**As linhas sugeridas trazem o comando sozinho**, com o nome do cliente na
linha de cima:

```
APOIO TIROL TESOURARIA FILIAL 503  (partição)
/relatorio 155
```

Na primeira versão era `/relatorio 155 — APOIO TIROL TESOURARIA...` numa
linha só. No Telegram o técnico copia a linha inteira, e chegava
`/relatorio 155 — APOIO TIROL TESOURARIA FILIAL 503` — que o bot lê como
nome de cliente e não acha. O que o bot imprime tem que ser exatamente o
que ele aceita; há teste fechando esse ciclo ponta a ponta.

Na produção real: 138 contas principais, 188 com as partições — 50 setores
que antes não apareciam em lugar nenhum.

`listar_todas_contas(incluir_particoes=True)` é **opt-in**: ligar por
padrão duplicaria conta e trocaria o `cue_iid` em relatórios, BI e
Relatório do Técnico, que contam com uma linha por local.

### 4.3 Os dois formatos do relatório

`.xls` nativo e `.pdf`, do **mesmo** `linhas_do_export` — se um divergisse
do outro, o técnico não saberia em qual acreditar. O `.xls` mantém as
cores da plataforma e abre no PC; o PDF (reportlab, paisagem, cabeçalho
repetido por página) abre no celular sem app de planilha. A legenda com o
resumo vai só no primeiro, para não repetir no chat. O nome do arquivo sai do
número da conta — como a partição tem número próprio, dois setores do
mesmo local já geram arquivos distintos.

O zoneamento vai em `<pre>` para as colunas não desalinharem no celular;
zoneamento grande é quebrado em várias mensagens (limite de 4096 do
Telegram), cada pedaço no seu próprio `<pre>` — um `<pre>` aberto numa
mensagem não continua na seguinte.

## 5. Settings (`bot_*`)

`bot_ativado` (false), `bot_tecnicos_ids` (vazio), `bot_relatorio_dias_padrao`
(7), `bot_relatorio_codigos` (CLO,OPN,BUR,BYP,ROP,RCL — mesmos do Relatório
do Técnico), `bot_cooldown_segundos` (10), `bot_update_offset` (confirmação
do polling; persistida para não reprocessar comando antigo ao reiniciar).

Config em **Configurações → Bot do Técnico (Telegram)**, só admin. Reusa o
bot/token já cifrado do Telegram — sem segredo novo.

## 6. Fases

| Fase | Entrega | Prova |
|---|---|---|
| **BT1** ✅ | `domain/bot_comandos.py` + `domain/zoneamento.py` | Unit: parsing (`@bot`, caixa, desconhecido), conta vs dias, resolução por número/nome/acento, ambiguidade não chuta, formatação alinhada |
| **BT2** ✅ | `listar_zonas` + `buscar_updates`/`enviar_documento` | Unit dos clients contra respostas fake: filtro exato do HAR, offset/timeout do polling, chat_id específico não muda os alertas |
| **BT3** ✅ | `telegram_bot_service.py` + worker no scheduler | Integração: autorização por remetente, negado é auditado, cooldown por usuário, portal fora do ar, sessão expirada, offset avança, fila descartada ao ligar, erro num comando não derruba o loop |
| **BT4** ✅ | Config admin + docs | Integração web (salva, desliga, id inválido descartado, auditoria sem os IDs) + screenshots claro/escuro |

| **BT5** ✅ | Correções do primeiro dia em produção: `/relatorio` usava `buscar_historico` (sem filtro de conta) para o resumo, e a sessão reaproveitada nunca relogava — o portal responde 500, não 401, e o bot emudecia até reiniciar | Integração: `/relatorio` não chama `buscar_historico`, sessão vencida reloga e o comando passa, portal fora de verdade desiste depois de uma tentativa, falha registra o que foi pedido |

| **BT6** ✅ | Partições (`domain/contas.py`, `/clientes`, `conta/partição` em `/zona` e `/relatorio`) + relatório em `.xls` **e** `.pdf` | Unit: leitura defensiva de `cue_nparticion`, agrupamento, escolha, listagem/filtro; integração: conta com partições pergunta em vez de chutar, `95/2` usa o `cue_iid` da partição, `/clientes` pede as partições ao portal, `/relatorio` manda os dois arquivos do mesmo conteúdo |

| **BT7** ✅ | Modelo de partição corrigido contra a base real (`debug_particoes.py`): partição é conta própria, `cue_nparticion` é o `cue_iid` da mãe, vínculo por `madre_ncuenta` — a sintaxe `95/2` inventada na BT6 foi removida | Unit com o formato real do portal (número próprio, vínculo com a mãe, `cue_nparticion=0` é principal, mãe apontando pra si é ignorada) + integração (pedir a mãe pergunta, pedir a partição resolve direto) |

| **BT8** ✅ | Corrige o laço da conta mãe (número explícito resolve direto; só a busca por nome pergunta) e as linhas sugeridas, que quebravam ao serem copiadas inteiras | Regressão unit + integração: `/relatorio 154` gera em vez de perguntar, nome da mãe ainda pergunta, e a linha impressa pelo bot é reprocessada e resolve |

## 7. Em aberto

- **Dependência nova**: `reportlab` (pura Python, instala com pip no
  Windows) para o PDF. Requer `pip install -r requirements.txt` no deploy.
- `scripts/debug_particoes.py` fica no repositório: se a base ganhar um
  arranjo de partição diferente do observado, ele mostra os campos crus
  sem supor formato nenhum.
