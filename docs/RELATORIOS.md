# Módulos de Relatórios — Atendimentos e Disparos Aleatórios

Extensão da arquitetura de [`ARQUITETURA.md`](ARQUITETURA.md) — mesmos
princípios (camadas domain/integrations/services/web, regras de negócio
puras e testáveis sem rede, tudo no banco, auditoria em tudo). Especificação
de origem: complemento "Módulos de Relatórios" do prompt principal.

## 1. Visão geral

Dois módulos novos no mesmo site, com a mesma sidebar/login/papéis:

| Módulo | O que gera | Para quê |
|---|---|---|
| **Atendimentos** | Atendimentos NYE/NYC concluídos no período: cliente, resolução, tempo, monitor + aba DESCARTADOS | Produtividade da equipe de monitoramento |
| **Disparos** | Uma linha por cliente com disparos BUR válidos no período: quantidade, horário de cada disparo, zonas, tempo de conclusão | Locais com disparos aleatórios |

Ambos: seletor de período, botão "Gerar relatório" (execução única por vez,
com feedback), prévia na tela idêntica ao Excel, download .xlsx, histórico
de gerações com re-download, configurações (admin) e auditoria.

## 2. Camadas

### 2.1 `integrations/softguard_client.py` (estender o existente)

Dois métodos novos, mesma sessão/login/retry/paginação já validados:

- `buscar_historico(codigos_alarme, desde, hasta)` →
  `GET /Rest/Search/ReporteHistorico` com `FechaDesde`/`FechaHasta`
  (`MM-DD-YYYY HH:MM:SS`), `CodigosAlarma`, `table=p_recepcion`,
  `OrdenarFecha=DESC`, `Mostrar=5000`, paginação `page/start/limit` até
  `total` (mesmo padrão envelope `rows` já corrigido em produção).
- `buscar_timeline(id_evento)` →
  `GET /Rest/search/EventoTimeLineFull?IdEvento=<rec_iid>&limit=500`.

### 2.2 `domain/atendimentos.py` (puro, sem I/O)

Regras A.3, funções sobre listas de dicts brutos:

- `analisar_timeline(passos)` → início (`etl_cAccion == "Inicio"`),
  fechamento (`etl_iAccionCode == "122"` OU "processado" no texto OU
  `Autoproceso`), monitor (`ope_cnombre`; `Autoproceso` ⇒ "Automático"),
  situação (último `IngresoComentarios` manual até o fechamento, ignorando
  os iniciados por "--- PROCEDIMENTO"), tempo (`HH"H"MM"M"SS"S"` —
  padronizado com o módulo B).
- `classificar_atendimento(...)` → incluído / descartado(motivo) / aberto.
  Descartes: fechamento automático por CLO; resolução indicando arme
  (lista configurável: `ativado`, `armado remotamente`, `armamento
  confirmado`) **com tratamento de negação** ("ainda não foi ativado" NÃO
  é arme). Prefixo do dia (`SEG:`…`DOM:`) na situação.

### 2.3 `domain/disparos.py` (puro, sem I/O)

Regras B.3, sobre eventos BUR/CLO/CLV/ROP/OPN/OPV/RCL agrupados por
`rec_iidcuenta`:

- disparo = BUR; conta TODOS os válidos (sem agrupar);
- exclui BUR até **5 min depois** de arme (CLO/CLV/ROP) e até **5 min
  antes** de desarme (OPN/OPV/RCL) — por isso a consulta leva folga de 6
  min em cada ponta do período; RCL (`Alarme Desarmado Remotamente`)
  confirmado como código real de desarme via app, validado contra dados
  de produção (22/07/2026);
- ciclo curto: se um arme é seguido de um desarme em **até 15 min**, todo
  disparo dentro desse ciclo é descartado (`MOTIVO_CICLO_CURTO`) — mesmo
  que fique fora das duas janelas de 5 min acima. Só se aplica quando o
  ciclo inteiro é curto (indício de teste/engano); um disparo ocorrido,
  por exemplo, 10 min após um arme que ficou horas armado **continua
  válido**, pois pode ser uma invasão real;
- ignora zonas com `PANICO`/`PÂNICO` na descrição (sem acento,
  case-insensitive; lista configurável);
- ocorrência: `ALEATORIO`, ou `ALEATORIO E RECORRENTE` a partir de
  `limite_recorrente` (padrão 15);
- zonas distintas por cliente a partir de `_zon_cdescripcion`;
- `horarios`: todos os `quando` dos disparos válidos (não só os
  atendidos), do mais antigo pro mais recente — pedido explícito da
  operação pra ver o horário de cada disparo, não só a quantidade; a
  planilha empilha um por linha na célula (mesmo formato que `zonas`
  já usa), com data porque um período manual pode passar de um dia
  pro outro.

### 2.4 `services/report_service.py`

Orquestra: consulta → domínio → persistência → .xlsx → auditoria.

- Lock próprio por módulo (mesmo padrão do `collector_lock`) — um relatório
  por vez, segundo clique bloqueado com feedback;
- Para Atendimentos: busca timeline por evento (limitando concorrência a
  chamadas sequenciais — volume esperado de dezenas/poucas centenas);
- Para Disparos: janela móvel = `period_end` do último `report_runs`
  bem-sucedido do módulo **cujo period_end já passou** (persistido no
  banco, auditável) — um manual sobre período antigo não reseta o
  encadeamento pra trás, e um manual com fim no futuro (ex.: "hoje" gerado
  de manhã) não trava os automáticos seguintes numa data que ainda não
  chegou; primeira vez = `horas_primeira_execucao` (padrão 24h) para trás;
  override manual na UI (aceita hora/minuto, não só o dia);
  tempo de conclusão e tempo para ligar via timeline dos disparos com
  `rec_ioperador != 0`, do mais recente para trás até achar,
  respectivamente, fechamento real (regra do módulo A) e uma chamada
  registrada (texto "chamada" na linha do tempo — validado contra timeline
  real, evento MIL-0172, "Chamada Atendida - Bem Sucedida"); cada um cai
  no "X" (preenchimento manual) só se não achar o marcador correspondente;
- .xlsx com **openpyxl** (dependência nova): cabeçalho verde `#21A366`
  texto branco, primeira linha congelada, auto-filtro, quebra de texto
  (SITUAÇÃO / ZONA); Atendimentos com 2ª aba DESCARTADOS
  (`DATA | CONTA | CLIENTE | EVENTO | MOTIVO`);
- Arquivos em `instance/reports/<modulo>/<timestamp>.xlsx`; metadados no
  banco; retenção usa o mesmo `retention_days` (job diário existente
  passa a apagar também `report_runs` antigos + seus arquivos).

### 2.5 Web (`web/reports/`)

Blueprint `reports`, duas páginas (`/relatorios/atendimentos`,
`/relatorios/disparos`) na sidebar para **admin e operador**:

- seletor de período com presets (ontem, últimos 7 dias, manual);
  Disparos default "desde o último relatório";
- POST "Gerar relatório" → serviço (lock + auditoria `report_generated`
  com módulo, período e contagens) → redireciona para a prévia;
- prévia paginada com as mesmas colunas do Excel + contadores (Disparos:
  total de disparos e nº de clientes; Atendimentos: nº de descartados);
- download do .xlsx da geração + histórico de gerações (data, usuário,
  período, linhas, re-download do arquivo arquivado);
- configurações A.5/B.5 na tela de Configurações existente (só admin),
  gravadas na tabela `settings` com validação e auditoria como as demais.

## 3. Modelo de dados (adições)

```mermaid
erDiagram
    USERS ||--o{ REPORT_RUNS : generated_by
    REPORT_RUNS {
        int id PK
        string module "atendimentos|disparos"
        datetime generated_at
        int generated_by_user_id FK
        datetime period_start
        datetime period_end
        string status "running|success|error"
        string error_message
        int row_count
        json extra_counts "descartados/total_disparos/clientes..."
        string file_path
    }
```

- Config nova (chaves na tabela `settings` existente):
  Atendimentos — `atend_codigos_evento` (NYE,NYC), `atend_incluir_automaticos`
  (false), `atend_incluir_abertos` (false), `atend_resolucao_indica_arme`
  (lista); Disparos — `disp_horas_primeira_execucao` (24),
  `disp_limite_recorrente` (15), `disp_ignorar_zonas` (PANICO).
- Janela móvel dos Disparos: derivada de `report_runs` (sem chave solta).

## 4. Fases (cada uma termina testada e commitada)

| Fase | Entrega | Marco testável |
|---|---|---|
| **R1** | Cliente SoftGuard (2 endpoints) + `domain/atendimentos.py` | Fixtures de timeline reais cobrindo os aceites: CLO/"ativado" descartado com motivo, "ainda não foi ativado" incluído, monitor Automático, prefixo de dia, tempo padronizado |
| **R2** | `domain/disparos.py` | Fixtures cobrindo: BUR 5 min pós-arme/pré-desarme excluído, zona pânico excluída (com/sem acento), contagem sem agrupar, recorrente ≥ 15 |
| **R3** | `report_runs` (migration) + `report_service` + .xlsx (openpyxl) + retenção | Gerar os dois relatórios contra fixtures ponta a ponta; arquivo abre com estilo correto; janela móvel encadeia (`period_start` = `period_end` anterior) |
| **R4** | Páginas web (prévia, histórico, download, configs) + auditoria + visual | Aceites de UI: prévia = Excel, histórico com quem/quando/período, download de arquivado, segundo clique bloqueado, operador gera mas não configura; screenshots claro/escuro |

## 5. Riscos/decisões em aberto

- **Formatos reais da API**: campos e formatos de `ReporteHistorico`/
  `EventoTimeLineFull` seguem o HAR descrito no prompt; como no módulo 1
  (caso `rows` vs `data`), a validação final é contra o portal real — o
  primeiro teste ao vivo pode revelar ajustes de parsing (por isso os dois
  endpoints entram na Fase R1, testáveis por fixture e substituíveis).
- **Volume**: `Mostrar=5000` + timeline por evento pode dar muitas chamadas
  em períodos longos; o serviço processa sequencialmente com timeout/retry
  do cliente existente e reporta progresso; se ficar lento na prática,
  otimizamos (cache/threads) numa iteração seguinte.
