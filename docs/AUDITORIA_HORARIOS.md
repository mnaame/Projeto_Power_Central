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
cadastradas da conta. **Lista vazia = conta sem horário.** É só isso.

## 3. Escopo: todas as contas

A varredura cobre **a base inteira**, residência inclusive.

Houve uma primeira versão que auditava só as contas comerciais, partindo da
ideia de que residência não tem arme programado. Quem opera a base quis ver
todas. Isso apagou junto a consulta ao catálogo `t_CuentasTipoServicio` e a
camada que adivinhava o nome do campo de tipo entre as grafias do portal —
que era justamente a parte do módulo nunca validada contra dados reais.
Menos código, menos uma chamada ao portal, menos uma suposição.

O recorte que sobrou é o filtro por **número/nome**, para reconferir um
cliente sem varrer tudo de novo. Em branco, varre tudo.

## 4. Camadas

### 4.1 `app/domain/horarios.py` (puro)

`tem_horario` / `resumo_horario` (contagem + primeira faixa, para a coluna
de referência), o predicado `nome_casa` e a dataclass `ContaAuditada`.

### 4.2 `app/integrations/softguard_client.py`

`listar_horarios(cue_iid)` → `/rest/search/Horario`, filtro
`hor_iidcuenta`, via `_buscar_paginado` (mesmo padrão dos outros
`buscar_*`/`listar_*`).

### 4.3 `app/services/auditoria_horarios_service.py`

`auditar(*, config, busca)` faz a varredura com **um login** reaproveitado
e devolve `{"sem", "com", "erros", "total"}`.

**Falha numa conta não derruba a varredura** (mesma disciplina do
`tecnico_service.gerar_lote`): a conta entra na contagem de `erros` e a
varredura segue. Auditoria que morre no meio não serve para nada.

`salvar_snapshot` / `ultimo_snapshot` / `resultado_do_snapshot` guardam e
recuperam o último resultado; `registrar_auditoria` grava a execução com
**só contadores** (`action` ≤ 48 chars, nada de nome de cliente).

### 4.4 Web — blueprint `auditoria_horarios` (`/auditoria-horarios`)

`index` (GET) mostra o último resultado, `rodar` (POST) executa e
`exportar` gera o `.xlsx` com a aba **"SEM horário"** primeiro (o
entregável, com conta e nome) e **"COM horário"** como referência (com o
resumo da faixa).

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

O comportamento do endpoint de horário para uma conta **sem** horário veio
do HAR e da leitura do código, **não de uma medição em produção** — e a
regra do módulo depende inteiramente dele. `scripts/debug_horarios.py`
confere numa amostra se conta sem horário responde lista vazia (e não
erro).

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
| `horarios_pausa_segundos` | `0` | Pausa entre contas, se o portal reclamar do ritmo |
