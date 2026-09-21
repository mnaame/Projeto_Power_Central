# Módulo: Auditoria de Horários

Extensão de [`ARQUITETURA.md`](ARQUITETURA.md) — mesmas camadas, mesma
disciplina. Varre todas as contas da PowerCentral e mostra quais estão
**sem horário de arme/desarme cadastrado**, sem abrir conta por conta.

## 1. O problema

O portal não tem tela de "contas sem horário". Para saber, alguém abre
conta por conta — o que na prática significa que ninguém sabe. Conta
comercial sem horário cadastrado é monitoramento cego: não existe "não
abriu hoje" nem "não fechou", porque não há horário esperado para comparar.

## 2. A regra, em uma linha

`/rest/search/Horario` filtrado por `hor_iidcuenta` devolve as faixas
cadastradas da conta. **Lista vazia = conta sem horário.** É só isso — o
resto do módulo existe por causa do tipo de conta.

## 3. Tipo de conta: a parte que separa "falta" de "não precisa"

Residência normalmente **não tem** arme/desarme programado. Auditar tudo
encheria a lista de conta que não está errada, e uma lista assim não é
lida. Por isso o padrão recorta em **Comercial**
(`horarios_tipos_auditar`), e a tela deixa incluir outros tipos.

De onde vem o tipo: o `CuentaByDealer` identifica por **número** — é o
mesmo campo que o filtro da tela "Falha TST" já usa em `_tip_nTipo` — e a
descrição legível sai do catálogo `t_CuentasTipoServicio`, que é uma
chamada só para a base inteira.

Como o portal varia a grafia dos campos entre telas, `domain/horarios.py`
procura por uma **lista de nomes candidatos**, sem diferenciar maiúscula de
minúscula. Campo ausente não vira erro: vira `TIPO_DESCONHECIDO` (`—`).

> **Conta de tipo desconhecido nunca é escondida pelo filtro.** Se o portal
> não disse o que a conta é, sumir com ela de um recorte "Comercial"
> transformaria uma limitação da integração em conta não auditada — que é
> exatamente o erro que o módulo existe para evitar. Antes aparecer a mais.

Se o catálogo falhar, o módulo continua entregando o principal (a lista de
quem está sem horário); só o filtro por tipo perde a serventia, e aí vale o
filtro por número/nome, que independe do tipo.

## 4. Camadas

### 4.1 `app/domain/horarios.py` (puro)

`tem_horario` / `resumo_horario` (contagem + primeira faixa, para a coluna
de referência), `catalogo_de_tipos`, `tipo_da_conta`, os predicados
`tipo_aceito` / `nome_casa` e a dataclass `ContaAuditada`.

### 4.2 `app/integrations/softguard_client.py`

- `listar_horarios(cue_iid)` → `/rest/search/Horario`, filtro
  `hor_iidcuenta`, via `_buscar_paginado` (mesmo padrão dos outros
  `buscar_*`/`listar_*`).
- `listar_tipos_servico()` → catálogo `t_CuentasTipoServicio`.

### 4.3 `app/services/auditoria_horarios_service.py`

`auditar(*, config, tipos, busca)` faz a varredura com **um login**
reaproveitado e devolve `{"sem", "com", "erros", "total", "tipos"}`.

Duas decisões que valem registro:

- **Falha numa conta não derruba a varredura** (mesma disciplina do
  `tecnico_service.gerar_lote`): a conta entra na contagem de `erros` e a
  varredura segue. Auditoria que morre no meio não serve para nada.
- **O recorte por tipo acontece antes da consulta**, não depois: conta que
  não precisa de horário não gasta uma ida ao portal.

`salvar_snapshot` / `ultimo_snapshot` / `resultado_do_snapshot` guardam e
recuperam o último resultado; `registrar_auditoria` grava a execução com
**só contadores** (`action` ≤ 48 chars, nada de nome de cliente).

### 4.4 Web — blueprint `auditoria_horarios` (`/auditoria-horarios`)

`index` (GET) mostra o último resultado, `rodar` (POST) executa e
`exportar` gera o `.xlsx` com a aba **"SEM horário"** primeiro (o
entregável) e **"COM horário"** como referência.

`rodar` **grava um snapshot e redireciona** em vez de renderizar direto
(POST/Redirect/GET). A varredura consulta o portal uma vez por conta e leva
minutos: assim o resultado fica salvo, a tela sobrevive a um navegador que
cansou de esperar, e um F5 não dispara tudo de novo.

## 5. Card "Saúde do cadastro" no dashboard

Lê do snapshot (`AuditoriaHorarioSnapshot`) e mostra "X contas sem horário"
com "atualizado em &lt;data&gt;". **Nunca roda a varredura no carregamento
do dashboard** — há um teste que quebra se alguém ligar isso por engano.
Sem snapshot, o card convida a rodar a auditoria.

## 6. O que ainda não foi medido contra o portal

Os nomes exatos dos campos de tipo e o comportamento do endpoint de horário
para conta sem horário vieram do HAR e da leitura do código, **não de uma
medição em produção**. `scripts/debug_horarios.py` fecha essa lacuna: mostra
quais campos existem de verdade, como o tipo fica resolvido por conta e o
que o endpoint devolve numa amostra.

```powershell
Stop-Service PowerCentral
.venv\Scripts\python.exe scripts\debug_horarios.py
Start-Service PowerCentral
```

Vale rodar **antes** de confiar na primeira lista — principalmente para
conferir uma conta que você sabe que tem horário cadastrado.

## 7. Configuração

| Chave | Padrão | Para quê |
|---|---|---|
| `horarios_tipos_auditar` | `Comercial` | Tipos auditados por padrão |
| `horarios_pausa_segundos` | `0` | Pausa entre contas, se o portal reclamar do ritmo |
