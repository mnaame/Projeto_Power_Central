# Módulo: Links da Central do Cliente (Auvo)

Extensão de [`ARQUITETURA.md`](ARQUITETURA.md) — mesmas camadas, mesma
disciplina. Especificação de origem: complemento "Links da Central do
Cliente (Auvo)". **Módulo de maior risco do sistema**: cria contatos reais
na Auvo, cada um com um link de acesso **sem login e sem senha**, via um
endpoint interno não documentado (autenticado por cookie de sessão do
painel, não pela API oficial).

## 0. Postura do módulo (por quê é diferente dos outros)

Todos os outros módulos do site são leitura ou escrita "segura" (abrir
tarefa de despacho é reversível e auditável pela própria Auvo). Este
módulo cria **acesso de terceiro sem autenticação** — um erro vaza o
painel de um cliente para outro. Por isso:

- **Admin-only** em toda rota de escrita (`@roles_required("admin")`).
- **Simulação LIGADA por padrão** (`central_simulacao=true`) — igual ao
  padrão já usado em `auvo_simulacao`.
- **Pré-visualização obrigatória** antes de qualquer envio — nada é
  criado sem a lista exata passar na tela primeiro.
- **Confirmação explícita** (checkbox) para desligar simulação, mesmo
  padrão de `auvo.alternar_modo`.
- **Cookie de sessão nunca persiste em claro** — colado pelo admin a cada
  execução, usado só naquela requisição, descartado depois. Nunca no
  banco, no `.env`, no repositório ou no `details` de auditoria.
- **Cliente HTTP isolado** (`auvo_painel_client.py`, separado do
  `auvo_client.py` oficial) — quando o endpoint não-oficial quebrar (a
  Auvo pode mudar sem aviso), o estrago fica contido num arquivo.

## 1. Fluxo (envelopa o processo do complemento original)

1. **Origem = `AuvoDepara`** (não CSV — a armadilha "Excel corrompe o
   CSV" do prompt original não existe aqui: não há CSV no meio).
   Elegível automaticamente: `status == "OK"` e `score >= score_minimo`
   (config, padrão 0.70). REVISAR/NAO/score baixo só entram com marcação
   humana explícita na tela de preparação.
2. **Dedup por `id_auvo`**: exclui quem já tem uma linha `CentralClienteLink`
   com `status == "criado"` (idempotência real — re-rodar não duplica;
   uma tentativa que falhou antes PODE ser re-tentada).
3. **Preparar/pré-visualizar** (`POST /central-cliente/preparar`): monta a
   lista elegível, mostra tabela (cliente, id_auvo, login, link que seria
   gerado, menus) — sem tocar a Auvo. O admin marca quais entram.
4. **Executar** (`POST /central-cliente/executar`, admin): exige colar o
   cookie de sessão + `auvo-user-request` daquela execução, e — só quando
   simulação está desligada — marcar a confirmação. Enquanto
   `central_simulacao=true`, "executar" sempre simula (mesma disciplina do
   botão de produção da Auvo).
5. Cria contato por contato, pausa configurável entre requisições (padrão
   1s), falha isolada por cliente (não derruba o lote), aborta o lote
   inteiro se detectar cookie expirado (sem marcar ninguém como criado a
   partir daquele ponto).
6. Grava em `CentralClienteLote`/`CentralClienteLink`, auditoria de cada
   criação, exportação em xlsx do lote.

## 2. Camadas

### 2.1 `app/domain/central_cliente.py` (lógica pura)

- `gerar_identificador() -> str`: `uuid.uuid4()` padrão (8-4-4-4-**12**
  hex). **NÃO CONFIRMADO contra um link real** — o complemento original
  suspeita que a Auvo usa 13 dígitos no último bloco; função isolada de
  propósito para trocar a implementação num só lugar quando confirmado
  (§6 — playbook).
- `montar_url(identificador: str) -> str`: `URL_BASE + "/" + identificador`
  (`URL_BASE = "https://novomillenium.auvo.com.br/share"`, constante do
  módulo).
- `elegivel_automatico(status, score, *, score_minimo) -> bool`: só
  `status == "OK"` e `score is not None` e `score >= score_minimo`.

### 2.2 `app/models/central_cliente.py` + migration

Mesmo padrão de `TecnicoLote`/`TecnicoLoteItem` (lote + itens, falha
isolada, não upsert):

- `CentralClienteLote`: id, criado_em, criado_por_user_id, simulacao
  (bool), status (`running/success/parcial/error`), total_itens,
  total_sucesso, total_falha, erro_mensagem.
- `CentralClienteLink`: id, lote_id (FK), id_auvo (indexado — **não**
  únique no banco: permite reter o histórico de tentativas falhas sem
  travar; a idempotência é uma regra de negócio em `montar_lote`, que só
  olha para linhas com `status == "criado"`), nome, contato_codigo,
  link_identificador, link_url, login (nullable), senha_cifrada
  (nullable — só populada se `central_gerar_login_senha=true`), menus
  (JSON), status (`pendente/criado/erro`), erro_mensagem, criado_em.

### 2.3 `app/integrations/auvo_painel_client.py` (isolado, não-oficial)

`CentralClientePainelClient.criar_contato_link(...)` — monta o
`POST .../SalvarContatoAdicionadoPeloModalNotificacoes` com
`Cookie` + `auvo-user-request` recebidos por parâmetro (nunca lidos de
config/banco). Detecta cookie expirado (resposta não-JSON ou `success`
ausente) e levanta `CentralClienteCookieExpiradoError` — o serviço aborta
o lote inteiro nesse caso, sem contar nada como criado a partir daí.

### 2.4 `app/services/central_cliente_service.py`

- `montar_lote(*, score_minimo, ids_extra=())` — lê `AuvoDepara`, aplica
  elegibilidade automática + IDs marcados manualmente, exclui quem já tem
  link `criado`. Devolve a lista de candidatos (sem tocar a Auvo).
- `criar_lote(candidatos, *, simulacao, user_id)` — cria
  `CentralClienteLote` + itens `pendente`, **commita imediatamente**
  (mesmo motivo do BI: o lote sobrevive mesmo se a execução falhar logo
  depois).
- `executar_lote(lote, *, credentials, config, pausa_segundos)` — em
  simulação, marca todos como `criado` sem chamar a Auvo (guarda o que
  SERIA enviado). Em produção, chama
  `CentralClientePainelClient.criar_contato_link` item a item, com pausa
  entre chamadas; cookie expirado aborta o restante do lote (itens
  restantes ficam `pendente`, não `erro` — não foram sequer tentados).
  Falha isolada por item (`status="erro"`, `erro_mensagem`) não impede os
  próximos.

## 3. Web — blueprint `central_cliente` (prefixo `/central-cliente`, admin-only)

- **`index`**: lotes recentes + formulário "Preparar novo lote"
  (score mínimo, IDs extra separados por vírgula).
- **`preparar`** (POST): mostra a pré-visualização (tabela com checkbox
  por linha, mesmo padrão de `tecnico/index.html` "puxar agenda" →
  "gerar") — nada é enviado ainda.
- **`executar`** (POST): campos cookie + `auvo-user-request` (prefill do
  setting, editável) + checkbox de confirmação (obrigatório só fora de
  simulação) + os itens selecionados (hidden inputs). Roda sincronamente
  (mesmo modelo do Relatório do Técnico — lotes são pequenos, é ação
  manual e rara).
- **`lote/<id>`**: detalhe (itens, status, erro por item).
- **`exportar/<id>`**: xlsx (cliente, id_auvo, login, link, contato_codigo,
  status) — documento sensível (login/link de acesso), mesmo cuidado do
  Cofre.
- **`configuracao`**: settings `central_*` + aviso de risco (mesmo tom do
  banner do Cofre) + link para o playbook de quebra (§6).

## 4. Settings (`settings_service.DEFAULTS`)

```
"central_simulacao": "true",
"central_score_minimo": "0.70",
"central_auvo_user_request": "",
"central_menu_solicitacoes": "true",
"central_menu_os": "true",
"central_menu_orcamento": "false",
"central_pausa_segundos": "1",
"central_cargo_padrao": "Cliente",
"central_gerar_login_senha": "false",
```

`central_gerar_login_senha` é uma decisão além do texto literal do
complemento, para encaixar a incerteza do §3.2 num config em vez de
travar o desenvolvimento: nasce **desligado** (não gera login/senha —
"menos segredo para proteger"), liga só depois de confirmar que a Auvo
exige. Se ligado, a senha gerada usa `app.domain.cofre.gerar_senha` (não
duplica gerador) e vai cifrada (`senha_cifrada`, Fernet com
`ENCRYPTION_KEY` — mesma chave das outras credenciais de integração, não
precisa de uma dedicada porque não é um cofre de acesso recorrente, é uma
senha gerada uma vez e não reexibida).

## 5. Segurança

- Cookie de sessão = senha da conta: nunca em log, nunca no `details` de
  auditoria, nunca persistido — parâmetro de função, descartado ao fim da
  requisição.
- Auditoria (`action` ≤ 48 chars, sem cookie/senha no `details`):
  `central_lote_preparado`, `central_lote_executado` (totais, não a
  lista completa), `central_link_criado` (por item: id_auvo, nome,
  contato_codigo — nunca a senha), `central_lote_exportado`,
  `central_config_saved`.
- `roles_required("admin")` em toda rota — o 403 automático já audita
  (`unauthorized_access_attempt`), não precisa de checagem por item como
  o Cofre (aqui é módulo inteiro, não registro a registro).
- `limiter` na rota `executar` (throttle de execuções reais).

## 6. Playbook de quebra / itens a confirmar antes de rodar de verdade

Ver §9 do complemento original — resumo do que só um humano confirma via
F12 antes da primeira execução real:

1. **Formato do identificador** (8-4-4-4-12 vs 13) — capturar um link
   real, comparar com `central_cliente.gerar_identificador()`.
2. **Login/Senha são exigidos?** — testar com campos vazios primeiro;
   só ligar `central_gerar_login_senha` se a Auvo recusar vazio.
3. **`central_auvo_user_request`** — id do usuário do painel.
4. Reconfirmar payload/endpoint se fizer semanas desde a última captura —
   `auvo_painel_client.py` é o único arquivo a mexer.

## 7. Fases

| Fase | Entrega | Prova |
|---|---|---|
| **LC1** | Domínio + modelos + migration + settings | Unit (identificador, url, elegibilidade) |
| **LC2** | `auvo_painel_client.py` + `central_cliente_service.py` | Integração: simulação não chama a Auvo, execução real com client fake, cookie expirado aborta o resto do lote, dedup por id_auvo, falha isolada |
| **LC3** | Aba web (preparar, executar, lote, exportar, configuração) | Integração web (admin-only, simulação por padrão) + screenshots claro/escuro |
| **LC4** | Docs (`OPERACAO.md`) + validação final | Suíte completa verde |

O que NUNCA entra no repositório: cookie de sessão real, credenciais reais
da Auvo, qualquer contato/link de cliente real.
