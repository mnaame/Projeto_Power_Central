# Módulo: Relatório do Técnico do Dia

Extensão de [`ARQUITETURA.md`](ARQUITETURA.md), [`RELATORIOS.md`](RELATORIOS.md)
e [`CHAMADOS_AUVO.md`](CHAMADOS_AUVO.md) — mesmas camadas, mesma disciplina
(regras puras testáveis sem rede, auditoria em tudo, erro isolado nunca
derruba o resto). Especificação de origem: complemento "Relatório do
Técnico do Dia". Envelopa o motor validado de `relatorio_tecnico.py` +
`auvo.listar_tarefas` — **preciso do script antes de implementar** (ver §6).

## 1. Diferença de forma para os outros módulos

Atendimentos/Disparos/Disparos Geral geram **um arquivo** por execução
(ReportRun 1:1 com o .xlsx). Este módulo gera **um arquivo por loja**, com
falhas independentes por loja — não é "1 relatório = 1 arquivo", é "1 lote
= N lojas, cada uma com seu status". Por isso entra um modelo novo
(`TecnicoLote` + `TecnicoLoteItem`), em vez de forçar no `ReportRun`.

Também é o primeiro módulo que:
- Lê a **agenda da Auvo** (não abre tarefa, lê as existentes).
- Faz **de-para reverso** (id Auvo → conta PowerCentral — a tabela
  `auvo_depara` já existe, é só consultar pelo lado contrário).
- Baixa da PowerCentral um **HTML disfarçado de .xls** (não JSON) — o
  arquivo final é literalmente a resposta crua, salva em disco.
- O usuário **escolhe o que baixar** (checkboxes) antes de gerar, e pode
  ajustar os códigos de evento **por loja** antes de confirmar.

## 2. Fluxo (§1 do complemento)

```
"Puxar agenda do dia" (data + técnico)
  → GET /tasks/ (Auvo, paramFilter startDate/endDate) — paginado
  → filtra pelo técnico (idUserTo, a confirmar contra o script)
  → para cada tarefa: customerId -> auvo_depara (reverso) -> conta_power
      sem vínculo? -> marca "sem_depara", não trava as demais
  → tabela na tela: loja | conta | horário | técnico | vínculo, com checkbox

usuário marca as lojas (+ opcional: ajusta códigos só de uma loja)
  → "Gerar selecionados"

para cada loja marcada (falha isolada, não derruba o lote):
  → conta_power -> cue_iid via CuentaByDealer (SoftGuard)
  → GET /handler/ExportReporteHistoricoExcel
      token=<cookie OAuth_Token>, CuentaReporte=<cue_iid>,
      CuentaNumero=<numero>, Codigoalarma=<códigos da loja>,
      FechaDesde/FechaHasta, dealerFirma=MIL, mostrar=5000, ...
  → salva a resposta (HTML) como <conta>_<nome>.xls
  → registra sucesso/erro no TecnicoLoteItem

"Baixar todos (.zip)" -> zip só das lojas selecionadas com sucesso
```

## 3. Camadas

### 3.1 `integrations/auvo_client.py` (estender)

- `_listar_paginado` ganha um parâmetro opcional `param_filter: dict` (hoje
  é sempre `{}`) — sem quebrar as 3 chamadas existentes (default `{}`).
- `listar_tarefas(data_inicio, data_fim)` → `GET /tasks/` com
  `paramFilter={"startDate": "YYYY-MM-DD", "endDate": "YYYY-MM-DD"}`,
  paginado, devolve as tarefas cruas (customerId, customerDescription,
  idUserTo, userToName, taskDate...).

### 3.2 `integrations/softguard_client.py` (estender)

- `buscar_conta_por_numero(numero)` → localizar o `cue_iid` (id interno) a
  partir do número da conta — via `CuentaByDealer` com filtro por
  `cue_ncuenta` (mesmo endpoint de `buscar_contas_em_falha_tst`, filtro
  diferente). **A confirmar o filtro exato contra o script** (a busca por
  TST usa `sta_ncuentaenfallo`; aqui precisa ser por número, sem esse
  filtro).
- `exportar_historico_html(*, cue_iid, numero, nome, desde, hasta,
  codigos_alarme)` → `GET /handler/ExportReporteHistoricoExcel` com o
  `token` = valor do cookie `OAuth_Token` da sessão logada (vai na query,
  não no header — diferente de todo o resto do client) + os demais
  parâmetros fixos do §1.4 do complemento. Devolve o corpo cru (str/bytes).
  Detecta erro de permissão pelo texto ("no se encontró la página" /
  "regularizar la situación") e levanta `SoftGuardError` com mensagem
  clara (é erro de perfil do usuário de integração, não bug).
- `listar_codigos_alarme()` → endpoint `codigosalarmas`, para popular o
  catálogo do multi-seletor (código → descrição) na tela.

### 3.3 `models/tecnico.py` (novo) + migration

- **`tecnico_lotes`**: `id`, `criado_em`, `criado_por_user_id`,
  `data_agenda`, `tecnico_id_auvo`, `tecnico_nome`, `periodo_desde`,
  `periodo_hasta`, `codigos_globais` (JSON), `status`
  (`running`/`success`/`parcial`/`error`).
- **`tecnico_lote_itens`**: `id`, `lote_id` (FK), `conta_power`,
  `id_auvo_cliente`, `nome_loja`, `codigos_usados` (JSON — herdados do
  lote ou override), `status`
  (`pendente`/`gerado`/`erro`/`sem_depara`/`nao_selecionado`),
  `erro_mensagem`, `arquivo_path`, `gerado_em`.

### 3.4 `services/tecnico_service.py` (novo)

- `buscar_agenda(*, config, data, tecnico_id, client=None) -> list[...]` —
  agenda da Auvo já cruzada com o de-para (reverso), marcando quem não tem
  vínculo. Não persiste nada ainda — é só para preencher a tela.
- `criar_lote(*, agenda_selecionada, codigos_globais, overrides,
  periodo, user_id) -> TecnicoLote` — grava o lote e os itens
  (`pendente`) para as lojas marcadas.
- `gerar_lote(*, lote, config, softguard_client=None) -> TecnicoLote` —
  para cada item `pendente`: resolve `cue_iid`, baixa o HTML, salva o
  arquivo, atualiza o item; erro em uma loja vira `erro` nela e segue para
  a próxima (try/except por item, igual ao padrão dos gatilhos Auvo).
  Login na SoftGuard uma vez só, reaproveitado em todas as lojas do lote.
- `montar_zip(lote) -> Path` — zip só dos itens `gerado` do lote.
- Lock de execução única por lote (mesmo padrão de `_executar_com_lock`),
  para não gerar o mesmo lote duas vezes em paralelo.

### 3.5 Web — aba "Relatório do Técnico" (`web/tecnico/`, prefixo `/tecnico`)

Página protegida (operador gera; admin configura), link na sidebar após
"Disparos Geral":

1. **Filtros**: data da agenda (padrão hoje), técnico (select com os
   usuários da Auvo — reaproveita `listar_usuarios`), período do
   histórico (preset "últimos 30 dias" + manual com hora), multi-seletor
   de códigos (catálogo de `listar_codigos_alarme`, padrão pré-marcado).
2. **"Puxar agenda do dia"** → tabela com checkbox por linha (loja | conta
   | horário | técnico | vínculo); linhas sem de-para aparecem
   desabilitadas com aviso e link direto para a Gestão do de-para
   (Chamados). "Marcar todas" / "Desmarcar todas". Botão "ajustar eventos"
   por linha abre um override dos códigos só daquela loja.
3. **"Gerar selecionados"** → cria o lote, executa, mostra progresso por
   loja (gerado/erro) — via polling simples (mesmo padrão de fragmento
   HTML recarregado do dashboard).
4. **Download**: link por loja pronta + "Baixar todos (.zip)".
5. **Histórico de lotes**: data/hora, quem gerou, técnico, data da
   agenda, período, nº de lojas geradas/erro, com re-download.
6. **Configurações (admin)**: técnico padrão, códigos padrão (lista com
   descrição), período padrão, toggle "oferecer .xlsx convertido"
   (opcional, fase separada — ver §5).

## 4. Settings novas

`tecnico_id_auvo_padrao` / `tecnico_nome_padrao`, `tecnico_codigos_padrao`
(padrão `CLO,OPN,BUR,BYP,ROP,RCL`), `tecnico_periodo_dias_padrao` (padrão
30), `tecnico_saida_xlsx_convertido` (bool, padrão false).

## 5. Fora do escopo da primeira entrega

A conversão opcional para `.xlsx` (§3 do complemento, "ciente de que a
conversão não reproduz 100% o visual") fica para depois de validar o fluxo
principal — o arquivo `.xls` (HTML nativo da plataforma) já é o formato
validado e idêntico ao export manual. Adiciono o toggle depois, se fizer
falta.

## 6. Preciso antes de começar

1. **O script `relatorio_tecnico.py`** (citado no §7 do complemento) —
   preciso dele para acertar com precisão: o filtro exato de
   `CuentaByDealer` por número de conta, o critério de match do técnico
   (por `idUserTo` ou por nome — o exemplo do complemento usa "Alfredo",
   um nome), a lista completa de parâmetros fixos do export, e como o
   script detecta o erro de permissão. Mesma disciplina dos módulos
   anteriores (`auvo.py`, `relatorio_disparos_geral.py`) — envelopar o
   motor validado, não adivinhar.
2. Se possível, **um exemplo de resposta do endpoint `codigosalarmas`**
   (ou uma tela do multi-seletor da própria plataforma), para eu montar
   o catálogo com os nomes certos.

## 7. Fases

| Fase | Entrega | Prova |
|---|---|---|
| **RT1** | Client SoftGuard/Auvo (novos métodos) + modelos + migration + settings | Unit dos clients com respostas fake (paginação da agenda, export HTML, erro de permissão) |
| **RT2** | `tecnico_service.py` completo (agenda + de-para reverso + geração por loja + zip) | Integração: agenda com/sem vínculo, geração com falha isolada por loja, zip só dos selecionados |
| **RT3** | Aba web completa (filtros, tabela com checkbox, override por loja, progresso, download, zip, histórico) | Integração web + screenshots claro/escuro |
| **RT4** | Config admin + docs (`OPERACAO.md`) + validação final | Suíte completa verde |

O que NUNCA entra no repositório: credenciais (já cobertas pelos módulos
anteriores), nomes reais de técnicos além do que já está nas configs.
