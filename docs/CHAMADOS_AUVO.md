# Módulo de Abertura de Chamados na Auvo

Extensão da arquitetura de [`ARQUITETURA.md`](ARQUITETURA.md) e
[`RELATORIOS.md`](RELATORIOS.md) — mesmas camadas
(domain/integrations/services/web), regras testáveis sem rede, tudo no
banco, auditoria em tudo. Especificação de origem: complemento "Abertura
de Chamados na Auvo". Substitui o stub `app/integrations/auvo.py` criado
na Fase 1.

## 1. Visão geral

Fecha o ciclo dos módulos de monitoramento: quando uma conta entra em
"sem comunicação real" (há tempo suficiente) ou acumula disparos
aleatórios demais, o sistema abre uma tarefa na Auvo para despachar
técnico — com de-para conta PowerCentral ↔ cliente Auvo, dedup por
cooldown, modo simulação (padrão LIGADO) e histórico/auditoria completos.

Fluxo de um chamado:

```
gatilho (coletor 5min | geração de disparos)
  → de-para OK? ──não──→ registra "sem_depara"
  → em cooldown? ──sim─→ registra "repetida"
  → simulação?   ──sim─→ registra "simulada" (NÃO grava dedup)
  → POST /tasks/ na Auvo
       ├─ 201 → registra "aberta" (id da tarefa; conta entra em cooldown)
       └─ erro → registra "falha" (corpo enviado + resposta, p/ diagnóstico)
```

## 2. Camadas

### 2.1 `integrations/auvo_client.py` (novo — substitui o stub)

Client HTTP isolado, mesmo padrão do `telegram_client.py` (exceção
dedicada `AuvoError` que nunca propaga como crash; timeout em toda
chamada). Encapsula as regras validadas em produção (§2 do complemento):

- **Login**: `GET /login/?apiKey=..&apiToken=..` → Bearer JWT em
  `result.accessToken`, válido 30 min. O client guarda o token com o
  horário de expiração e renova sozinho (margem de 5 min); em `401`
  refaz o login e repete a chamada uma vez.
- **Listas** (`/users/`, `/taskTypes/`, `/customers/`):
  `paramFilter={}` + `page` + `pageSize=50`, lendo `result.entityList`
  até `result.pagedSearchReturnData.totalItems` (mesmo espírito do
  paginador do SoftGuard).
- **`criar_tarefa(payload)`**: `POST /tasks/`, sucesso = HTTP 201.
  O client NÃO monta o payload (isso é do serviço) mas valida os tipos
  antes de enviar: `customerId`/`taskType`/`priority`/ids como **int**
  (string quebra a Auvo com 500), sem `keyWords`. Em erro, a exceção
  carrega corpo enviado + resposta, para o histórico.

### 2.2 `models/auvo.py` (novo) + migration

- **`auvo_depara`** — o de-para editável:
  `conta_power` (única, indexada), `nome_power`, `id_auvo` (int, nulo =
  não abre), `nome_auvo`, `score`, `status` (`OK` / `REVISAR` / `NAO`),
  `updated_at`, `updated_by_user_id`. Duas contas podem apontar para o
  mesmo `id_auvo` (loja + tesouraria — válido por especificação).
- **`auvo_chamados`** — histórico de cada tentativa:
  `criado_em`, `gatilho` (`sem_comunicacao`/`disparos`), `conta_power`,
  `cliente`, `resultado` (`aberta`/`simulada`/`falha`/`repetida`/
  `sem_depara`), `id_tarefa_auvo`, `origem_user_id` (nulo = robô),
  `request_body`/`response_body` (JSON, preenchidos em falha),
  `erro`. **O cooldown deriva desta tabela**: última linha `aberta`
  (criação real) da conta dentro de `cooldown_horas` bloqueia; linhas
  `simulada` nunca bloqueiam — atende "em simulação NÃO persistir o
  estado de dedup" sem tabela extra, e o histórico fica auditável.

### 2.3 `services/auvo_service.py` (novo)

Orquestração, sem I/O direto de rede (recebe o client):

- `abrir_chamado(gatilho, conta, nome, contexto, origem_user_id=None)` —
  o fluxo da §1; templates de título/descrição renderizados dos settings
  (título vira 1ª linha da `orientation`, como validado); auditoria em
  todo resultado.
- `processar_sem_comunicacao(contas_classificadas)` — chamado pelo ciclo
  do coletor: filtra contas sem comunicação há ≥
  `sem_comunicacao_horas_minimas` (padrão 3h).
- `processar_disparos(clientes)` — chamado após geração bem-sucedida do
  relatório de Disparos: filtra clientes com ≥ `disparos_minimos_tarefa`
  (padrão 5) disparos válidos.
- `testar_criacao()` — teste em níveis (mínimo → +cliente/tipo →
  +responsável), devolvendo a resposta de cada nível (a ferramenta que
  destravou a integração original).
- `regerar_depara()` — casa por similaridade de nome (difflib) os
  clientes da Auvo (via API) contra as contas conhecidas, marcando
  `OK`/`REVISAR`, **preservando linhas já revisadas por humano**.
- `importar_depara_csv(arquivo)` — importa o `depara_power_auvo.csv`
  do protótipo (`;`-separado) como carga inicial.

Gatilhos plugados sem acoplamento: erro na Auvo nunca derruba o ciclo do
coletor nem a geração de relatório (try/except + registro "falha").

### 2.4 Settings (chaves novas em `settings_service`)

`auvo_api_key` / `auvo_api_token` — **cifradas com Fernet**, mesmo
mecanismo das credenciais do Telegram; nunca em código/repositório.

Em claro: `auvo_simulacao` (**padrão true**), `auvo_criador_id`
(idUserFrom), `auvo_responsavel_id` (idUserTo), `auvo_atribuir_responsavel`
(bool — desligado ⇒ omite `idUserTo`, tarefa cai em "sem agendamento"),
`auvo_task_type`, `auvo_priority` (1/2/3, padrão 2),
`auvo_cooldown_horas` (12), `auvo_sem_comunicacao_horas_minimas` (3),
`auvo_disparos_minimos_tarefa` (5), e os 4 templates (título/descrição ×
sem-comunicação/disparos) com placeholders `{conta}`, `{nome}`,
`{desde}`, `{sinal}`, `{qtd}`, `{zonas}`.

### 2.5 Web — aba "Chamados (Auvo)" (`web/auvo/`, prefixo `/chamados`)

Página protegida (operador vê; admin configura), link na sidebar após
"Disparos":

1. **Cards de status**: modo (Simulação/Produção, destacado), tarefas
   abertas hoje, contas em cooldown, última execução + resultado.
2. **Chave Simulação ↔ Produção** (admin) com confirmação explícita ao
   ligar produção (despacha técnico de verdade).
3. **Configuração** (admin): credenciais mascaradas, IDs, réguas,
   templates + botões "Listar usuários" / "Listar tipos de tarefa" /
   "Listar clientes" (para descobrir os IDs sem sair do site).
4. **Botão "Testar criação"** (admin): o teste em níveis da §2.3, com a
   resposta de cada nível na tela.
5. **Gestão do de-para**: tabela com filtro/busca, edição de `id_auvo` e
   status, destaque para `REVISAR` e ids duplicados, botão "Regerar
   de-para", importação do CSV.
6. **Histórico de chamados**: data/hora, gatilho, conta, cliente, id da
   tarefa, origem (usuário/robô), resultado; em falha, corpo enviado +
   resposta visíveis para diagnóstico.

## 3. Aceites que os testes cobrem

| Aceite (complemento §8) | Verificação |
|---|---|
| Payload §2: ids numéricos, sem keyWords, 201 = sucesso | unit do client (validação de tipos) + integração com fake Auvo |
| `idUserTo` omitido quando `atribuir_responsavel` desligado | unit do serviço (payload montado) |
| Sem-comunicação só ≥ horas mínimas; disparos só ≥ mínimo | unit das réguas |
| Dedup: não reabre dentro do cooldown; simulação não grava dedup | integração (fluxos `aberta`→`repetida`; `simulada`→`aberta`) |
| Só de-para `OK` com id abre; `NAO`/vazio → `sem_depara` | integração do serviço |
| Token renova aos 30 min; 401 → relogin + retry | unit do client (fake clock/responses) |
| Falha guarda corpo + resposta; nunca derruba coletor/relatório | integração (fake que devolve 400/500) |
| Simulação/produção, edição do de-para, permissões admin/operador | integração web |

## 4. Fases (todas concluídas)

| Fase | Entrega | Prova |
|---|---|---|
| **C1** ✓ | `auvo_client.py` + modelos + migration + settings novos | Unit do client (login/renovação/401/paginação/validação de tipos) com respostas fake |
| **C2** ✓ | `auvo_service.py` completo + gatilhos plugados (coletor e disparos) | Integração: todos os resultados (`aberta`/`simulada`/`falha`/`repetida`/`sem_depara`), dedup, réguas, templates |
| **C3** ✓ | Aba web completa (cards, toggle c/ confirmação, config, teste em níveis, de-para, histórico) | Integração web + screenshots claro/escuro (Playwright) |
| **C4** ✓ | Retenção de `auvo_chamados` + docs (`OPERACAO.md` §5.2.2) | Suíte completa verde |

O histórico de chamados entra na retenção diária junto com ciclos,
auditoria e relatórios (mesma janela configurável, padrão 90 dias).

O que NUNCA entra no repositório: `AUVO_API_KEY`, `AUVO_API_TOKEN`,
ids reais de usuários — tudo via tela de configuração (cifrado no banco)
ou `.env` local.
