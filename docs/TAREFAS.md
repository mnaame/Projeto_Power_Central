# Módulo: Minhas Tarefas (Fixas / Semana / Dia)

Extensão de [`ARQUITETURA.md`](ARQUITETURA.md) — mesmas camadas, mesma
disciplina. Especificação de origem: "PROMPT — Módulo: Minhas Tarefas
(Fixas / Semana / Dia)". Aba de tarefas **pessoais** do usuário logado,
sem escrita em produção externa e sem chamada a API de terceiro — o
módulo de menor risco do sistema. Cada usuário só enxerga e edita as
próprias tarefas.

## 1. Isolamento por dono (o que rege o resto do módulo)

- **Toda leitura/escrita filtra por `user_id`.** Nunca se confia só no
  `id` da URL — `app/web/tarefas/routes.py:_carregar_ou_abort` carrega a
  tarefa pelo id e confere `tarefa.user_id == current_user.id` antes de
  qualquer ação; tarefa de outro usuário → `403` (não `404`, para não
  disfarçar — mas também não expõe conteúdo nenhum, só confirma que o id
  pertence a alguém).
- **Sem papel de admin.** `@login_required` simples — é pessoal, qualquer
  usuário autenticado (admin ou operador) tem sua própria lista.
- **Atrasada não é apagada nem movida sozinha.** É só a consulta de
  exibição que inclui `data < hoje AND status='pendente'` junto do
  horizonte atual — decisão de concluir/remarcar/mover é sempre humana.

## 2. Camadas

### 2.1 `app/domain/tarefas.py` (lógica pura)

- `semana_corrente(referencia) -> (segunda, domingo)`: semana ISO (segunda
  a domingo) que contém `referencia`.
- `esta_atrasada(data, status, *, horizonte, hoje) -> bool`: `status ==
  'pendente'` e o **período já encerrado**. Pra `dia`, período é o
  próprio dia (`data < hoje`). Pra `semana`, período é a semana inteira
  que contém `data` (`data < inicio_da_semana_corrente(hoje)`) — **não**
  `data < hoje` puro, que é o bug real corrigido (tarefa de Semana criada
  na segunda aparecia atrasada já na terça, sem a semana ter acabado).
  `fixa` nunca atrasa por aqui (não depende de `data`). Único lugar que
  decide "atrasada" — a tela (`tarefa_atrasada` em `app/web/filters.py`)
  e `tarefa_service.contar_dia` chamam essa função, não reimplementam.

### 2.2 `app/models/tarefa.py` (`Tarefa`) + migration `ecae4d947f47`

Campos conforme o complemento (§1): `user_id` (FK `users.id`, indexado),
`titulo`, `descricao`, `horizonte` (`CheckConstraint IN ('fixa', 'semana',
'dia')`), `data` (Date, nullable — usada em dia/semana, geralmente vazia
em fixa), `prioridade` (`CheckConstraint IN ('baixa', 'media', 'alta')`,
default `media`), `status` (`CheckConstraint IN ('pendente', 'feito')`,
default `pendente`), `ordem` (reservado pra fase 2 — arrastar), `criado_em`
(TZDateTime), `concluido_em` (TZDateTime, nullable — grava quando marca
feito, limpa se desmarcar).

### 2.3 `app/services/tarefa_service.py`

Toda função de leitura recebe `user_id` e filtra por ele; toda função de
escrita recebe o objeto `Tarefa` já carregado (a checagem de dono é feita
uma vez, na camada web, antes de chamar o serviço).

- `hoje() -> date` — "hoje" em `FUSO_HORARIO` (nunca UTC cru, senão a
  virada de dia sai errada).
- `listar_dia`/`listar_semana`/`listar_fixas(user_id, ...)` — cada um
  já inclui as atrasadas do próprio horizonte (pendente + `data` no
  passado); fixas não dependem de data, só de `status='pendente'`.
- `listar_concluidas_hoje(user_id, ...)` — feitas com `concluido_em`
  dentro do dia local, de qualquer horizonte (a tela agrupa por bloco).
- `contar_dia(user_id, ...) -> {"pendentes", "atrasadas"}` — usado pelo
  cartão do dashboard, sem carregar as tarefas inteiras.
- `query_historico(user_id) -> Query` — todas as concluídas (qualquer
  horizonte/data), mais recente primeiro; devolve a Query (não `.all()`)
  pra tela paginar (`Query.paginate`, mesmo padrão de `admin.auditoria`).
- `criar(*, user_id, titulo, horizonte, ...)` — adição rápida: só título +
  horizonte; `data` é preenchida sozinha (hoje pra Dia e pra Semana; Fixa
  fica sem data). Título vazio levanta `ValueError`.
- `atualizar`/`alternar_status`/`mover`/`excluir` — formulário completo,
  checkbox (concluir/desmarcar, grava ou limpa `concluido_em`), trocar de
  horizonte (ajusta `data` quando o novo horizonte depende dela) e
  exclusão definitiva.

## 3. Web — blueprint `tarefas` (prefixo `/tarefas`, `@login_required`)

- **`index` (GET)**: os três blocos (Dia/Semana/Fixas) lado a lado
  (`.tarefas-grid`, responsivo — empilha em telas estreitas), cada um com
  campo de adição rápida no topo (só título + Enter), lista com checkbox,
  chip de prioridade, destaque vermelho (`.is-atrasada`) pra atrasada com
  a data original, botões "→ Hoje"/"→ Semana"/"→ Fixa" e "excluir", e um
  `<details>` recolhido com as concluídas de hoje (riscadas, com checkbox
  pra desmarcar).
- **`criar` (POST)**: adição rápida — POST simples (sem WTForms, mesmo
  padrão de ações rápidas do resto do site), horizonte inválido → `400`,
  título vazio → flash de aviso, nada é criado.
- **`concluir`/`mover`/`excluir` (POST)**: alternam status, trocam
  horizonte, apagam — sempre via `_carregar_ou_abort` (dono + existência).
  Redirect volta pra `/tarefas#bloco-<horizonte>` (ancora), pra não perder
  a posição na tela depois da ação.
- **`editar` (GET/POST)**: formulário completo (`TarefaForm`, WTForms) —
  título, descrição, horizonte, data, prioridade. Mesma tela tem o botão
  "Excluir tarefa".
- **`historico` (GET, aceita `?pagina=`)**: todas as concluídas do
  usuário, mais recente primeiro, paginado (30/página — mesmo padrão de
  `admin.auditoria`, `HISTORICO_POR_PAGINA`). Link "Ver histórico" no
  topo do `index`. Cada linha tem "reabrir" (reusa a rota `concluir` —
  ela já alterna feito↔pendente, não precisou de rota nova).
- **Dashboard**: cartão "Suas tarefas de hoje" em `dashboard/_conteudo.html`
  (só aparece se houver pendente) com a contagem do Dia + chip de
  atrasadas, linkando pra `/tarefas#bloco-dia`. Reusa `contar_dia` — não
  duplica a regra de atrasada.

## 4. Fases

| Fase | Entrega | Prova |
|---|---|---|
| **TF1** ✅ | Domínio + modelo + migration (`ecae4d947f47`) | Unit (`semana_corrente`/`esta_atrasada`) |
| **TF2** ✅ | `tarefa_service.py` (queries por horizonte, criar/atualizar/concluir/mover/excluir) | Integração (isolamento por dono, atrasada aparece e não some, fixa sem data) |
| **TF3** ✅ | Aba web completa (3 blocos, adição rápida, ações, editar) + link na sidebar | Integração web (RBAC de dono — 403/404, horizonte inválido — 400) + screenshots claro/escuro |
| **TF4** ✅ | Cartão no dashboard + docs + validação final | Suíte completa verde |
| **TF5** ✅ | Corrige `esta_atrasada` pra levar o horizonte em conta (bug real: Semana atrasava a cada dia, não só quando a semana acabava) + tela `historico` paginada | Unit (`esta_atrasada` por horizonte, cobrindo os 7 dias da mesma semana) + integração (isolamento por dono, ordenação, paginação, "reabrir") + screenshots claro/escuro |

Módulo concluído. Fase 2 (não implementada, caminho aberto pelo campo
`ordem` e pelo modelo simples): recorrência (`recorrencia` + job que
recria a próxima ocorrência ao concluir), ordenação por arrastar,
atribuir tarefa a um colega (viraria tarefa de equipe — fora de escopo
deste módulo pessoal).
