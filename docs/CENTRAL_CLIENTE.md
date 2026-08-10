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
   com `status == "criado"` **num lote real** (`simulacao == False`) —
   idempotência de verdade (re-rodar não duplica; uma tentativa que
   falhou antes PODE ser re-tentada). Um `criado` de lote em **simulação**
   NÃO exclui: simular não pode ter efeito nenhum sobre o que ainda pode
   ser rodado de verdade (bug corrigido em 07/08/2026 — a query original
   não distinguia simulação de execução real).
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
6. **Telefone**: busca `phoneNumber` do cliente pela **API oficial**
   (`AuvoClient`, não o endpoint interno) e normaliza pro formato do
   WhatsApp (§5.5) — grava em `CentralClienteLink.telefone`. Falha nessa
   busca nunca derruba o lote, só deixa o WhatsApp indisponível para
   aquele item.
7. Grava em `CentralClienteLote`/`CentralClienteLink`, auditoria de cada
   criação, exportação em xlsx do lote (agora com telefone). Cada linha
   com telefone válido ganha o botão "Enviar no WhatsApp" (§5.5).

## 2. Camadas

### 2.1 `app/domain/central_cliente.py` (lógica pura)

- `gerar_identificador() -> str`: formato **confirmado via F12** (§6):
  8-4-4-4-**13** em hex, gerado com `secrets` (não `uuid.uuid4()`/`random`)
  — não é UUID v4 padrão (que seria 12 no último grupo).
- `montar_url(identificador: str) -> str`: `URL_BASE + "/" + identificador`
  (`URL_BASE = "https://novomillenium.auvo.com.br/share"`, constante do
  módulo).
- `elegivel_automatico(status, score, *, score_minimo) -> bool`: só
  `status == "OK"` e `score is not None` e `score >= score_minimo`.
- `normalizar_telefone(bruto, *, ddi="55") -> str | None`: tira tudo que
  não é dígito, prefixa o DDI se faltar; devolve `None` se não sobrar um
  telefone plausível (Brasil: 12 ou 13 dígitos no total) — melhor não
  mostrar o botão de WhatsApp do que abrir no contato errado.
- `montar_link_whatsapp(telefone, mensagem) -> str`: `https://wa.me/<telefone>?text=<mensagem urlencoded>`.
  Só monta o link — nunca dispara nada sozinho (§5.5).

### 2.2 `app/models/central_cliente.py` + migration

Mesmo padrão de `TecnicoLote`/`TecnicoLoteItem` (lote + itens, falha
isolada, não upsert):

- `CentralClienteLote`: id, criado_em, criado_por_user_id, simulacao
  (bool), status (`running/success/parcial/error`), total_itens,
  total_sucesso, total_falha, erro_mensagem.
- `CentralClienteLink`: id, lote_id (FK), id_auvo (indexado — **não**
  únique no banco: permite reter o histórico de tentativas falhas sem
  travar; a idempotência é uma regra de negócio em `montar_lote`, que só
  olha para linhas com `status == "criado"` **de lotes com
  `simulacao == False`**), nome, contato_codigo,
  link_identificador, link_url, login (nullable), senha_cifrada
  (nullable — só populada se `central_gerar_login_senha=true`), telefone
  (nullable, já normalizado — busca via API oficial em `executar_lote`,
  ver §1 passo 6), menus (JSON), status (`pendente/criado/erro`),
  erro_mensagem, criado_em.

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
- `buscar_clientes(termo, *, limite=30)` — lookup por nome/conta/id_auvo,
  **sem** os filtros de `montar_lote` (não exige elegibilidade, não
  exclui quem já tem link — pelo contrário, mostra o link existente).
  Existe porque, sem isso, um cliente já processado simplesmente some de
  qualquer busca (é excluído por `montar_lote`) e parece que nunca
  existiu — bug de UX reportado em produção (cliente de teste "sumiu" ao
  procurar de novo pelo ID). Usada pela busca na tela `index`.
- `criar_lote(candidatos, *, simulacao, user_id)` — cria
  `CentralClienteLote` + itens `pendente`, **commita imediatamente**
  (mesmo motivo do BI: o lote sobrevive mesmo se a execução falhar logo
  depois).
- `executar_lote(lote, *, credentials, config, pausa_segundos, auvo_client=None)` —
  em simulação, marca todos como `criado` sem chamar a Auvo (guarda o que
  SERIA enviado). Em produção, chama
  `CentralClientePainelClient.criar_contato_link` item a item, com pausa
  entre chamadas; cookie expirado aborta o restante do lote (itens
  restantes ficam `pendente`, não `erro` — não foram sequer tentados).
  Falha isolada por item (`status="erro"`, `erro_mensagem`) não impede os
  próximos. Roda em ambos os modos (simulação e produção): busca telefone
  na API **oficial** (`auvo_client`, ou `auvo_service.criar_cliente(config)`
  se não passado) e normaliza — falha nessa busca (credenciais oficiais
  não configuradas, erro de rede) nunca derruba o lote, só zera o mapa de
  telefones daquela execução.
- `renderizar_mensagem_whatsapp(*, nome, link, login="", senha="")` —
  template configurável (`central_whatsapp_template`) com placeholder
  desconhecido ficando literal (mesmo truque de `auvo_service._Contexto`,
  reimplementado localmente).
- `montar_link_whatsapp_item(item, *, config) -> str | None` — decifra a
  senha (se houver), renderiza a mensagem e monta o link `wa.me`; `None`
  se o item não tem telefone válido.

## 3. Web — blueprint `central_cliente` (prefixo `/central-cliente`, admin-only)

- **`index`** (aceita `?q=` GET): lotes recentes + "Buscar cliente"
  (nome, conta ou id_auvo — `buscar_clientes`, mostra "já tem link" com
  link pro lote em vez de simplesmente sumir) + formulário "Preparar novo
  lote" (score mínimo, IDs extra separados por vírgula). Resultado da
  busca sem link tem botão "Usar este ID" (JS mínimo, `app.js`) que
  copia o id_auvo pro campo "IDs Auvo extra" — sem precisar decorar o
  número.
- **`preparar`** (POST): mostra a pré-visualização (tabela com checkbox
  por linha, mesmo padrão de `tecnico/index.html` "puxar agenda" →
  "gerar") — nada é enviado ainda.
- **`executar`** (POST): campos cookie + `auvo-user-request` (prefill do
  setting, editável) + checkbox de confirmação (obrigatório só fora de
  simulação) + os itens selecionados (hidden inputs). Roda sincronamente
  (mesmo modelo do Relatório do Técnico — lotes são pequenos, é ação
  manual e rara).
- **`lote/<id>`**: detalhe (itens, status, erro por item). Cada linha
  `criado` com telefone válido ganha o botão "Enviar no WhatsApp";
  `criado` sem telefone mostra "sem telefone" (nunca esconde a linha).
- **`lote/<id>/item/<id>/whatsapp`**: **não** é um link direto pro
  `wa.me` — é uma rota do próprio site que audita
  (`central_whatsapp_aberto`) e só então redireciona (302) pro `wa.me`
  com a mensagem pronta. Garante o registro de auditoria mesmo sendo um
  `<a target="_blank">` simples, sem precisar de JS. 404 se o item não
  tiver telefone (o botão não deveria nem estar visível nesse caso) ou
  não pertencer ao lote da URL.
- **`exportar/<id>`**: xlsx (cliente, id_auvo, telefone, login, link,
  contato_codigo, status) — documento sensível (login/link de acesso),
  mesmo cuidado do Cofre.
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
"central_whatsapp_ddi": "55",
"central_whatsapp_template": "Ola, {nome}! ... {link} ...",
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

`central_whatsapp_ddi`/`central_whatsapp_template`: DDI padrão pra
normalização (`normalizar_telefone`) e o texto da mensagem, com
placeholders `{nome}`/`{link}`/`{login}`/`{senha}` — os dois últimos só
fazem sentido se `central_gerar_login_senha=true` (o template padrão não
os cita, já que o acesso confirmado é só por link).

## 5. Segurança

- Cookie de sessão = senha da conta: nunca em log, nunca no `details` de
  auditoria, nunca persistido — parâmetro de função, descartado ao fim da
  requisição.
- Auditoria (`action` ≤ 48 chars, sem cookie/senha no `details`):
  `central_lote_preparado`, `central_lote_executado` (totais, não a
  lista completa), `central_link_criado` (por item: id_auvo, nome,
  contato_codigo — nunca a senha), `central_lote_exportado`,
  `central_config_saved`, `central_whatsapp_aberto` (id_auvo/nome —
  nunca o telefone completo nem a mensagem).
- `roles_required("admin")` em toda rota — o 403 automático já audita
  (`unauthorized_access_attempt`), não precisa de checagem por item como
  o Cofre (aqui é módulo inteiro, não registro a registro).
- `limiter` na rota `executar` (throttle de execuções reais).

## 5.5 WhatsApp assistido (wa.me) — "clique-e-envie"

Envio é **assistido, não automático** (decisão deliberada do complemento):
o site monta a mensagem pronta e abre o WhatsApp já com o contato e o
texto preenchidos; **um humano confere e envia**. Isso mantém a trava
contra mandar o link do cliente errado, e evita risco de banimento do
número (disparo em massa por robô viola as regras do WhatsApp). **Não**
usa bibliotecas não-oficiais (whatsapp-web.js e afins) — só o link público
`https://wa.me/<telefone>?text=<mensagem>`.

Telefone vem da API **oficial** da Auvo (`AuvoClient.listar_clientes()`,
campo `phoneNumber`), buscado uma vez por execução do lote e normalizado
(`normalizar_telefone`) — nunca do endpoint interno. Envio 100% automático
(API oficial do WhatsApp Business, com templates aprovados pela Meta) fica
como evolução futura — não implementado agora.

## 6. Playbook de quebra / itens a confirmar antes de rodar de verdade

Ver §9 do complemento original — resumo do que só um humano confirma via
F12 antes da primeira execução real:

1. ✅ **CONFIRMADO (07/08/2026)** — Formato do identificador: **8-4-4-4-13**
   hex, não UUID padrão (12 no último grupo). Capturado de um `LinkAcesso`
   real (`d9f316b4-93b1-4f1f-a3bf-dc2ebe529a200`) via F12 num contato de
   teste. `central_cliente.gerar_identificador()` já gera nesse formato
   (`secrets`, não `uuid.uuid4()`).
2. ✅ **CONFIRMADO (07/08/2026)** — Login/Senha **podem ir vazios**; a
   Auvo aceita e cria o contato normalmente (`Login: ""`, `Senha: ""` no
   payload capturado, resposta de sucesso). `central_gerar_login_senha`
   continua **desligado** por padrão — não é mais só cautela, é o
   comportamento confirmado como correto.
3. ✅ **CONFIRMADO (07/08/2026)** — `auvo-user-request` capturado:
   `238031` (id do usuário logado no painel na hora do teste). Precisa
   ser colocado em Configuração → "ID do usuário do painel" antes de
   rodar em produção (cada usuário do painel tem o seu; se quem for
   rodar o lote for outra pessoa, capturar de novo).
4. Reconfirmar payload/endpoint se fizer semanas desde a última captura —
   `auvo_painel_client.py` é o único arquivo a mexer. Formato de resposta
   (`success`/`codigo`/`mensagem`) ainda não foi conferido byte a byte
   contra uma captura real — o parsing em `auvo_painel_client.py` segue o
   que o complemento original descreveu; validar na primeira execução
   real (ainda em simulação é seguro testar o parsing manualmente contra
   a aba "Resposta" do F12).

> Restou o formato exato do JSON de resposta (`success`, `codigo`,
> `mensagem`) não conferido pixel a pixel — os 3 itens acima, que eram os
> bloqueadores reais, estão confirmados. Ainda assim, mantenha a primeira
> execução em produção pequena (1-2 clientes) e confira o resultado antes
> de rodar um lote grande.

## 7. Fases

| Fase | Entrega | Prova |
|---|---|---|
| **LC1** ✅ | Domínio + modelos + migration + settings | Unit (identificador, url, elegibilidade) |
| **LC2** ✅ | `auvo_painel_client.py` + `central_cliente_service.py` | Integração: simulação não chama a Auvo, execução real com client fake, cookie expirado aborta o resto do lote, dedup por id_auvo, falha isolada |
| **LC3** ✅ | Aba web (preparar, executar, lote, exportar, configuração) | Integração web (admin-only, simulação por padrão) + screenshots claro/escuro |
| **LC4** ✅ | Docs (`OPERACAO.md`) + validação final | Suíte completa verde |
| **LC5** ✅ | WhatsApp assistido (wa.me) + telefone normalizado via API oficial | Unit (normalizar_telefone, montar_link_whatsapp) + integração (busca de telefone não derruba o lote, mensagem com template, rota audita+redireciona, 404 sem telefone) + screenshots claro/escuro |

Módulo implementado, coberto por teste, e com os 3 itens bloqueadores do
§6 **confirmados via F12 contra um contato de teste real** (formato do
identificador, Login/Senha vazios, `auvo-user-request`). Ainda não
rodou um lote de produção de verdade — recomendação é começar pequeno
(1-2 clientes) e conferir o resultado antes de um lote maior.
`admin.auditoria` (tela genérica já existente) cobre
`central_lote_preparado`/`central_lote_executado`/`central_link_criado`/
`central_lote_exportado`/`central_config_saved`/`central_modo_alterado`/
`central_whatsapp_aberto` sem precisar de tela própria.

O que NUNCA entra no repositório: cookie de sessão real, credenciais reais
da Auvo, qualquer contato/link de cliente real.
