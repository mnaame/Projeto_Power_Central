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
- `resolver_conta(termo, mapa_contas)`: aceita número (`95`, `0095` — mesma
  normalização de conta do resto do sistema) ou parte do nome (sem acento,
  sem caixa). **Ambiguidade nunca vira chute**: com mais de um cliente
  casando, devolve `RESOLUCAO_AMBIGUA` com as candidatas e o bot pede o
  número. Mandar o zoneamento da loja errada é vazar o mapa de segurança de
  um cliente para outro. Nome idêntico resolve a ambiguidade ("VILLEFORT
  HM" não fica preso porque existe "VILLEFORT HM DEPOSITO").

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

## 4. Comandos

| Comando | O que faz |
|---|---|
| `/relatorio <conta> [dias]` | Histórico de eventos: arquivo `.xls` nativo (com as cores da plataforma) via `sendDocument` + resumo curto na legenda (conta, período, nº de eventos — contado do próprio arquivo, ver §4.1) |
| `/zona <conta ou nome>` | Zoneamento completo, em texto monoespaçado |
| `/ajuda` | Lista os comandos (não consome cooldown) |

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

## 7. Em aberto

- **Relatório em PDF** (`bot_saida_pdf` do complemento original) **não foi
  implementado**: converter o HTML nativo em PDF exige uma dependência
  nova (wkhtmltopdf/WeasyPrint), que no Windows é instalação à parte. O
  `.xls` nativo — que é o padrão pedido no próprio complemento — está
  entregue. Decidir a ferramenta antes de implementar; uma chave de config
  que não faz nada seria pior que a ausência dela.
- **`/zona <conta> completo`** (incluir as partições) fica como fase 2, já
  previsto no complemento.
