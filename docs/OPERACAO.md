# Manual de Operação — Power Central

Guia para a equipe de suporte da Novo Millenium instalar, operar e resolver
problemas do sistema de monitoramento de comunicação de alarmes. Não
assume conhecimento prévio de programação — comandos são copiar-e-colar.

Para entender **como o sistema é construído por dentro** (arquitetura,
modelo de dados, decisões técnicas), veja
[`docs/ARQUITETURA.md`](ARQUITETURA.md). Este documento aqui é só sobre
**instalar e operar no dia a dia**.

---

## 1. O que este sistema faz

Monitora, a cada 5 minutos (configurável), os clientes que a central marcou
em "Falha de TST" no portal SoftGuard/PowerCentral, separa quem está
**realmente sem comunicação** de quem é **falso positivo** (não manda o
auto-teste, mas segue comunicando normalmente), avisa a equipe no Telegram
quando essa lista muda, e mostra tudo num painel web com login.

## 2. Pré-requisitos

- Windows 10/11 ou Windows Server, com acesso à internet (para instalar as
  dependências Python na primeira vez).
- [Python 3.12 ou mais recente](https://www.python.org/downloads/) instalado
  (marque "Add python.exe to PATH" no instalador).
- Git (para baixar/atualizar o código) — ou receber o código por outro meio.
- Uma conta de integração **somente-leitura** no portal SoftGuard.
- Um bot do Telegram (criado com o [@BotFather](https://t.me/BotFather)) e o
  ID do grupo/canal de alertas.
- Para instalar como serviço: [NSSM](https://nssm.cc/download) (baixe o
  `.zip`, extraia `nssm.exe` — usaremos a versão win64).

## 3. Instalação (primeira vez)

Abra o PowerShell na pasta onde o projeto vai ficar (ex.: `C:\power_central`).

```powershell
git clone <url-do-repositorio> C:\power_central
cd C:\power_central

python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

### 3.1 Configurar segredos (`.env`)

```powershell
Copy-Item .env.example .env
notepad .env
```

Preencha:

- `SECRET_KEY`: qualquer texto longo e aleatório (usado para proteger a sessão de login).
- `ENCRYPTION_KEY`: gere com `.venv\Scripts\python.exe -m flask generate-key` e cole o resultado.
- `VAULT_ENCRYPTION_KEY`: só necessária se for usar a aba **Cofre de
  Senhas** (§5.2.5) — gere do mesmo jeito (`flask generate-key`, chave
  **diferente** da `ENCRYPTION_KEY` acima). Se perder essa chave depois de
  cadastrar senhas no cofre, elas ficam irrecuperáveis — não é um "esqueci
  a senha", é cifragem de verdade. Guarde uma cópia num lugar **separado**
  do backup do banco de dados (§6).
- `SOFTGUARD_HOST`, `SOFTGUARD_PORT`, `SOFTGUARD_CLIENT_ID`, `SOFTGUARD_USERNAME`, `SOFTGUARD_PASSWORD`: dados da conta de integração do portal.

> O token do bot e o chat ID do Telegram **não** vão no `.env` — são
> configurados depois, pela própria interface web (tela Configurações,
> só admin vê), e ficam salvos cifrados no banco.

### 3.2 Criar o banco de dados

```powershell
$env:FLASK_APP = "app:create_app"
.venv\Scripts\python.exe -m flask db upgrade
```

### 3.3 Criar o primeiro administrador

```powershell
.venv\Scripts\python.exe -m flask seed-admin
```

Vai pedir um nome de usuário e uma senha (mínimo 8 caracteres).

### 3.4 Testar antes de instalar como serviço

```powershell
.venv\Scripts\python.exe -m flask run
```

Abra `http://127.0.0.1:5000` no navegador e faça login com o admin criado
acima. Para testar o coletor sem mexer no portal real:

```powershell
.venv\Scripts\python.exe -m flask collect --dry-run
```

Se tudo estiver certo, pare o `flask run` (Ctrl+C) e siga para a instalação
como serviço.

### 3.5 Mostrar rapidinho para alguém na mesma rede (sem instalar nada)

Para uma demonstração pontual (ex.: mostrar para o chefe, no mesmo
escritório/wifi), sem instalar como serviço nem mexer em HTTPS:

```powershell
.venv\Scripts\python.exe -m flask run --host=0.0.0.0 --port=5000
```

Descubra o IP da sua máquina na rede local:

```powershell
ipconfig
```

Procure "Endereço IPv4" (algo como `192.168.0.42`). A outra pessoa, **na
mesma rede**, acessa em `http://192.168.0.42:5000` (troque pelo IP real).
Na primeira vez, o Windows Firewall costuma perguntar se libera o
Python/porta em "redes privadas" — clique em Permitir.

Isso é só para teste pontual: some quando você fecha o `flask run`
(Ctrl+C), e o tráfego não é criptografado (aceitável dentro de uma rede
interna confiável, mas não deixe assim de forma permanente). Para algo
que fique no ar sozinho, veja a seção 4 abaixo.

## 4. Instalar como serviço do Windows

O serviço mantém o sistema rodando sozinho, inclusive depois de reiniciar a
máquina, sem precisar de ninguém logado.

1. Baixe o NSSM em <https://nssm.cc/download>, extraia `nssm.exe` (pasta
   `win64`) para dentro de `C:\power_central\scripts\` (ou em qualquer
   pasta do PATH do sistema).
2. Abra o PowerShell **como Administrador**.
3. Rode:

```powershell
cd C:\power_central\scripts
.\install_service.ps1 -InstallPath "C:\power_central" -Port 8000
```

O script aplica as migrations, registra o serviço `PowerCentral` com
reinício automático em caso de falha, e já inicia o serviço. Por padrão o
serviço só aceita conexão da própria máquina (`127.0.0.1`). Para que
outros computadores da **mesma rede local** também acessem (sem HTTPS —
igual à seção 3.5, só que permanente), acrescente `-BindHost "0.0.0.0"`:

```powershell
.\install_service.ps1 -InstallPath "C:\power_central" -Port 8000 -BindHost "0.0.0.0"
```

O script já libera a porta no firewall e mostra o IP para acessar. Para
HTTPS (interno ou de fora da rede), mantenha o padrão `127.0.0.1` e use
as seções 4.1/4.2 abaixo.

Para conferir se está rodando:

```powershell
Get-Service PowerCentral
```

Deve mostrar `Status: Running`. Se não existe nenhum admin ainda, crie um
com `.venv\Scripts\python.exe -m flask seed-admin` (mesmo passo do item 3.3).

Para desinstalar o serviço (não apaga banco nem arquivos):

```powershell
.\uninstall_service.ps1
```

### 4.1 HTTPS só na rede interna (Caddy)

Por padrão o serviço escuta só em `127.0.0.1:8000` (não é alcançável por
outros computadores, nem da rede nem da internet). Para acesso da equipe
via rede interna com HTTPS, sem sair da rede da empresa, use um reverse
proxy — [Caddy](https://caddyserver.com/) é o mais simples:

1. Baixe o Caddy (executável único) e coloque em `C:\caddy\caddy.exe`.
2. Copie `scripts/Caddyfile.example` para `C:\caddy\Caddyfile` e ajuste o
   endereço (`power-central.novomillenium.local`, ou o IP da máquina).
3. Rode `C:\caddy\caddy.exe run` (ou instale o Caddy como serviço também,
   com o mesmo NSSM).
4. Na primeira vez, o Caddy gera um certificado próprio (`tls internal`).
   O navegador vai avisar que o certificado não é confiável até você
   instalar o certificado raiz do Caddy nas máquinas da equipe — o Caddy
   deixa esse certificado em `%ProgramData%\Caddy\pki\authorities\local\root.crt`;
   distribua-o via GPO ou manualmente (Gerenciador de Certificados do
   Windows → Autoridades de Certificação Raiz Confiáveis → Importar).

### 4.2 Acesso de fora da rede (Cloudflare Tunnel)

Para acessar o painel de fora da rede da empresa (ex.: gestor no celular,
suporte remoto), sem abrir porta nenhuma no roteador/firewall, use o
[Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/).
O `cloudflared` roda na mesma máquina do serviço, faz uma conexão de saída
para a Cloudflare, e é a Cloudflare quem expõe o endereço público com
HTTPS válido — nada entra na sua rede, só sai.

**Pré-requisito**: um domínio associado à sua conta Cloudflare (grátis —
se ainda não tem nenhum, dá para registrar um barato em qualquer
registrador e apontar os nameservers para a Cloudflare, ou usar um
subdomínio de um domínio que a empresa já tenha).

1. Instale o `cloudflared`:
   ```powershell
   winget install --id Cloudflare.cloudflared
   ```
   (ou baixe o `.msi` em <https://github.com/cloudflare/cloudflared/releases>)

2. Autentique com a conta Cloudflare (abre o navegador):
   ```powershell
   cloudflared tunnel login
   ```

3. Crie o túnel nomeado:
   ```powershell
   cloudflared tunnel create power-central
   ```
   Isso gera um ID de túnel e um arquivo de credenciais em
   `%UserProfile%\.cloudflared\`. Anote o ID.

4. Copie `scripts/cloudflared-config.example.yml` para
   `%UserProfile%\.cloudflared\config.yml` e ajuste `tunnel`,
   `credentials-file` e `hostname` com os seus dados.

5. Aponte o DNS (cria o registro automaticamente na Cloudflare):
   ```powershell
   cloudflared tunnel route dns power-central power-central.suaempresa.com.br
   ```

6. Instale como serviço Windows (sobrevive a reinício, igual ao serviço
   do Power Central):
   ```powershell
   cloudflared service install
   ```

7. Teste de fora da rede (ex.: com o wifi do celular desligado, usando
   dados móveis): `https://power-central.suaempresa.com.br` deve abrir a
   tela de login, com cadeado válido.

Depois de configurar o túnel, **ajuste o `.env`** — o tráfego agora chega
por HTTPS de verdade (a Cloudflare termina o TLS na borda dela):

```
FLASK_ENV=production
SESSION_COOKIE_SECURE=true
```

E reinicie o serviço: `Restart-Service PowerCentral`. Sem
`SESSION_COOKIE_SECURE=true`, o cookie de sessão continuaria aceitando
conexão insegura — inofensivo enquanto só a rede interna acessava, mas
importante agora que o link é público.

#### Camada extra fortemente recomendada: Cloudflare Access

Os dados deste painel mostram **quais locais estão com o alarme sem
comunicação agora** — informação sensível do ponto de vista de segurança
física, não um painel qualquer. Antes de divulgar o link publicamente,
adicione o [Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/policies/access/)
(gratuito até 50 usuários): ele exige confirmação de e-mail corporativo
**antes** da requisição sequer chegar no servidor — um bot varrendo a
internet nunca vê nem a tela de login do sistema.

1. No painel Cloudflare → **Zero Trust** → **Access** → **Applications** →
   **Add an application** → **Self-hosted**.
2. Domínio: o mesmo do túnel (`power-central.suaempresa.com.br`).
3. Política: **Allow** para e-mails do domínio da empresa (ex.:
   `@novomillenium.com.br`) ou uma lista específica de e-mails da equipe.
4. Salvar.

A partir daí, o acesso vira duas camadas: e-mail corporativo confirmado
pela Cloudflare primeiro, login do Power Central depois.

> Estes passos dependem do painel da própria Cloudflare (login na conta,
> DNS, políticas de Access) — precisam ser feitos por alguém com acesso à
> conta da empresa lá, não é algo automatizável por fora.

## 5. Uso do dia a dia

### 5.1 Papéis

- **Operador**: vê o painel, dispara "Atualizar agora".
- **Administrador**: tudo que o operador faz, mais gestão de usuários,
  configurações (janela de horas, códigos comprovadores, intervalo do
  coletor, Telegram) e auditoria.

### 5.2 Painel

Mostra quantos clientes estão **sem comunicação real agora** (o número que
importa), quantos são falsos positivos, o status do último ciclo e do
último alerta enviado, um gráfico de evolução, e a lista detalhada. Atualiza
sozinho a cada 30 segundos; o botão **Atualizar agora** força um ciclo na
hora (tem um intervalo mínimo entre cliques, configurável).

### 5.2.1 Relatórios (Atendimentos e Disparos)

Duas páginas na barra lateral, para operador e admin:

- **Atendimentos**: escolha o período (ontem, últimos 7 dias ou manual) e
  clique "Gerar relatório". A prévia na tela é idêntica ao Excel; o botão
  "Baixar Excel" traz o arquivo com a aba principal e a aba DESCARTADOS
  (eventos fora do relatório, com o motivo — ex.: cliente armou).
- **Disparos**: por padrão cobre "desde o último relatório até agora"
  (janela móvel — o próximo começa onde o anterior terminou); também
  aceita período manual com data **e hora/minuto** (diferente de
  Atendimentos, que é por dia inteiro). Uma linha por cliente, com
  quantidade, zonas, tempo de conclusão e **tempo para ligar para o
  cliente** — ambos automáticos, lidos da linha do tempo do disparo mais
  recente atendido (fica "X" só quando não há chamada/fechamento
  registrado nela). A coluna "CONCLUSÃO MONITORAMENTO DISPARO." continua
  para o monitor preencher no Excel.

Cada geração fica no **Histórico de gerações** (quem gerou, período,
linhas) com re-download do arquivo arquivado; tudo vai para a auditoria.
Os arquivos seguem a mesma retenção configurável (padrão 90 dias). As
regras dos dois módulos (códigos de evento, termos de arme, limite
recorrente, zonas ignoradas etc.) são editáveis em Configurações (admin).

**Disparos Geral (fechamento de fim de semana).** Diferente do Disparos
(Aleatórios), que conta só os disparos "puros", o **Disparos Geral** conta
**TODOS** os disparos de cada cliente e classifica cada um em *após arme* /
*seguido de desarme* / *aleatório*, montando o texto da OCORRENCIA (acima do
limite configurável — padrão 50 — vira "RECORRENTE"). A saída é um Excel com
**3 abas por grupo** (Villefort / Super Nosso+APOIO / Base, decididos pelo
nome — ajustável em Configurações). O período tem preset "fim de semana
atual" (sexta 18h → segunda 08h) e período manual com **data e hora**. A
prévia mostra os 3 grupos na tela. Ele também **abre chamado na Auvo** para
clientes acima de um limite próprio (Configuração da aba Chamados →
"Disparos Geral: mínimo de disparos para abrir") — como usa o mesmo gatilho
"disparos", a regra de não reabrir enquanto a ordem anterior está aberta
vale entre os dois relatórios (não duplica ordem para o mesmo local).

### 5.2.2 Chamados (Auvo)

A aba **Chamados** abre tarefas na Auvo automaticamente quando um cliente
fica sem comunicação real ou acumula disparos aleatórios demais — fechando
o ciclo do monitoramento até o despacho de um técnico.

**Botão "Verificar tudo agora"** (topo do painel, operador ou admin): roda
os dois gatilhos na hora, sem esperar o ciclo automático — o mesmo ciclo do
coletor que já verifica sem comunicação a cada 5 min, mais o relatório de
Disparos com a janela automática (desde o último até agora). Os dois têm
cooldown/lock independentes: se um estiver bloqueado (ex.: sem comunicação
em cooldown), o outro roda normalmente. Útil para lançar chamados novos de
disparo durante o dia, sem precisar ir até a aba de Disparos gerar o
relatório manualmente.

**Modo (importante).** Começa em **Simulação**: os gatilhos rodam e o
histórico registra "o que seria aberto", mas nada é enviado à Auvo. Só
depois de validar o de-para e o payload é que se liga o **modo Produção**
(em Configuração → Modo de operação), com uma confirmação explícita — em
produção, cada chamado despacha um técnico de verdade.

**Antes de ligar a produção** (tudo em Chamados → Configuração, só admin):

1. **Credenciais**: cole a apiKey e o apiToken da Auvo (ficam cifradas no
   banco, nunca no `.env` nem no git).
2. **IDs**: preencha o *criador* (idUserFrom — usuário com permissão de
   abrir tarefa), opcionalmente o *responsável* (idUserTo — usuário de
   campo que recebe) e o *tipo de tarefa*. Os botões "usuários", "tipos de
   tarefa" e "clientes" listam os IDs direto da Auvo. Se não houver
   responsável apto, deixe "Atribuir ao responsável" desligado — a tarefa
   cai em "Tarefas sem agendamento" na Auvo, para distribuição manual.
3. **Réguas**: cooldown (não reabre a mesma conta antes de X horas — padrão
   12), horas mínimas de sem-comunicação (padrão 3) e mínimo de disparos
   (padrão 5).
4. **Testar criação**: cria tarefas de teste **reais** na Auvo em níveis
   (mínimo → +cliente/tipo → +responsável), mostrando a resposta de cada —
   é a ferramenta para descobrir rapidamente qualquer campo errado antes de
   confiar no automático.

**De-para** (Chamados → Gestão do de-para): liga a conta da PowerCentral ao
cliente na Auvo. Só linhas **OK** com ID preenchido abrem chamado; **NAO**
não abre; **REVISAR** aguarda conferência (destacado). Importe o
`depara_power_auvo.csv` pelo botão, edite qualquer vínculo na própria
tabela, e use "Regerar de-para" para recasar por nome só as linhas ainda
não revisadas (as OK/NAO são preservadas). Duas contas podem apontar para o
mesmo cliente Auvo (ex.: loja + tesouraria) — isso é normal.

**Pausar uma conta (supressão temporária).** Quando um problema já está
sendo tratado em campo (aguardando o cliente, central que vai ser trocada
etc.), use o botão **Pausar** na coluna Supressão: a conta continua OK, mas
**não abre chamado** enquanto estiver pausada — nem por sem-comunicação nem
por disparos. Você pode informar uma **data** ("até quando", opcional) e um
**motivo**. Com data, a conta **volta a abrir sozinha** na virada do dia
seguinte; sem data, fica pausada até você clicar **Liberar**. O card
"Pausadas" e o link "ver só as pausadas" ajudam a acompanhar. Use isto
(em vez de NAO) para problemas temporários — assim você não corre o risco
de esquecer uma conta bloqueada para sempre. Para contas que saem de vez
(central retirada), aí sim use **NAO**.

> Dica ao ligar a produção pela primeira vez: pause as contas que já estão
> com problema conhecido/em atendimento **antes** de virar a chave, senão o
> sistema abrirá um chamado para cada uma delas no primeiro ciclo.

**Não repete ordem enquanto a anterior está aberta.** O sistema só abre uma
ordem nova para um local depois que a ordem anterior for **concluída na
Auvo** (`finished`/status Finalizada). Enquanto a ordem estiver aberta ou em
andamento, mesmo que o cliente continue com problema, nada de novo é aberto
— aparece como `repetida` no histórico. Assim que o técnico finaliza, se o
problema persistir, uma nova ordem é aberta. Isso vale por **local** (todas
as contas que apontam pro mesmo cliente Auvo contam como um só). Quando não
dá para checar o status na hora, um cooldown de tempo (padrão 12h) serve de
rede de segurança para não duplicar.

**Histórico** (painel): cada tentativa vira uma linha — `aberta` (criada de
verdade), `simulada`, `repetida` (já existe ordem aberta / dentro do
cooldown), `sem_depara` (conta sem vínculo OK) ou `falha` (com o corpo
enviado e a resposta da Auvo expandíveis, para diagnóstico). Segue a mesma
retenção dos relatórios.

### 5.2.3 Relatório do Técnico

A aba **Relatório do Técnico** prepara o técnico antes de ele sair para
visitar as lojas do dia: para cada loja na agenda dele na Auvo, baixa o
histórico da PowerCentral (arme, desarme, disparo, zona isolada, arme/
desarme remoto) — **um arquivo por loja**, no formato nativo da plataforma
(o mesmo que o export manual gera, com as cores por tipo de evento).

**Fluxo:**

1. Escolha a **data da agenda** (padrão hoje), o **técnico** (nome ou id —
   vazio pega todos), o **período do histórico** (padrão configurável de N
   dias antes da agenda, ou manual com hora) e os **códigos de evento**
   (lista separada por vírgula — o padrão cobre arme/desarme pelo painel e
   remoto, disparo e zona isolada).
2. **"Puxar agenda do dia"**: busca as tarefas da Auvo no dia e cruza com o
   de-para (a mesma tabela usada em Chamados). Cada linha mostra loja,
   conta, horário, técnico e o vínculo — lojas **sem vínculo OK no de-para**
   aparecem desmarcadas e desabilitadas, com um link direto para a Gestão
   do de-para (Chamados) resolver antes de gerar. Cada linha tem seu campo
   de códigos, pré-preenchido com o padrão — dá para ajustar só daquela
   loja antes de confirmar.
3. **"Gerar selecionados"**: baixa o histórico de cada loja marcada. Uma
   falha numa loja (ex.: conta sem `cue_iid`, ou a PowerCentral recusando o
   export por permissão) não derruba as demais — cada uma tem seu próprio
   status na tela seguinte (`gerado`/`erro`).
4. Na tela do lote: download por loja pronta, **"Baixar todos (.zip)"** com
   só as que geraram com sucesso, e o motivo do erro (quando houver) de cada
   loja que falhou.
5. A página inicial guarda o **histórico de lotes** (quem gerou, técnico,
   data da agenda, período, quantas lojas geraram) com link para reabrir
   qualquer lote e baixar de novo.

**Configuração** (Relatório do Técnico → Configuração, só admin): técnico
padrão, códigos de evento padrão e período padrão do histórico (em dias) —
só pré-preenchem os filtros da tela; cada geração pode ajustar à vontade.

### 5.2.4 Eficácia do Técnico (BI)

A aba **Eficácia do Técnico** responde a pergunta "o atendimento em campo
realmente reduziu os disparos do cliente?" Para cada ordem **concluída**
na Auvo numa loja com de-para OK, compara os disparos válidos por dia
(mesma régua da aba Disparos — exclui pânico, rotina de arme/desarme e
ciclo curto) numa janela **antes** e **depois** da conclusão (padrão 15
dias, normalizado por dia), e classifica: melhorou, piorou, estável, ou
sem base de comparação (cliente que já não disparava).

**"Recalcular"** é o passo pesado: busca a agenda concluída na Auvo e o
histórico de disparos na PowerCentral — pode levar alguns segundos. O
resultado fica salvo (não busca de novo a cada clique na tela); o
histórico de recálculos guarda os anteriores, com link para reabrir
qualquer um.

**O que a tela mostra:**
- KPIs: intervenções no período, % que melhorou, disparos evitados
  (estimativa) e clientes crônicos.
- Gráfico antes×depois por técnico e uma linha de tendência (disparos/dia
  depois de cada visita, em ordem cronológica).
- Ranking de técnicos — com aviso de **amostra pequena** quando o técnico
  teve poucas intervenções no período (não use isso isolado para decisão).
- Clientes crônicos: visitas repetidas (padrão 3+) e que ainda disparam.
- Tabela de intervenções, com avisos de **janela parcial** (a janela de
  "depois" ainda não fechou os dias todos — o número pode mudar) e
  **atribuição compartilhada** (duas visitas da mesma conta caindo na
  mesma janela — não creditar 100% a uma só). Ambas as tabelas (e a de
  clientes crônicos) têm botão de exportar para Excel.
- Cada linha tem um link "ver no Técnico", que leva pro Relatório do
  Técnico já com o técnico e a data da visita preenchidos, pronto pra
  puxar a agenda daquele dia e baixar o histórico colorido da loja.

**Configuração** (Eficácia do Técnico → Configuração, só admin): janela
antes/depois, limiares de melhora/piora, tipos de tarefa que contam como
intervenção (vazio = todos), visitas mínimas para virar crônico, período
padrão de análise e amostra mínima por técnico. A tela também deixa
ajustar janela e limiares por recálculo, em "avançado" — a configuração
aqui é só o padrão.

> **Importante antes de confiar no ranking para decisão**: o campo que
> identifica a **data de conclusão** da tarefa na Auvo ainda não foi
> confirmado contra produção (só o critério de "concluída ou não" foi).
> Rode `python scripts\debug_bi_data_conclusao.py <ID_DA_TAREFA>` numa
> tarefa que você sabe a data real da visita e confira se a data que o
> BI escolheu bate. Se não bater, ajuste os candidatos em
> `app/domain/bi.py` (`_CAMPOS_DATA_CONCLUSAO`) antes de usar os números
> para avaliar técnicos.

### 5.2.5 Cofre de Senhas

A aba **Cofre de Senhas** guarda credenciais de sistemas da empresa
(câmera/DVR, roteador, plataformas, e-mail, acessos de cliente) num só
lugar, cifradas no banco (nunca em claro), com controle por papel e
auditoria de todo acesso à senha.

- **Níveis**: `equipe` (qualquer usuário logado vê e revela) e `restrito`
  (só admin vê, revela, cria ou edita — inclusive marcar um item existente
  como restrito). Um operador tentando acessar um item restrito por link
  direto recebe "acesso negado" e isso fica registrado na auditoria.
- **Revelar/copiar** pede a **sua própria senha de novo**, mesmo já
  logado — camada extra barata contra tela esquecida aberta na mesa de
  alguém. A senha aparece só naquela resposta (nunca em mensagem de
  sucesso que fica na tela, nunca salva na sessão) e some da tela sozinha
  depois de ~30s; o botão "Copiar" limpa a área de transferência no mesmo
  prazo. Cada revelação — sucesso ou falha de reautenticação — fica na
  auditoria.
- **Criar/editar**: botão "Gerar senha forte" sugere uma senha aleatória
  forte (não precisa digitar); deixar o campo de senha em branco ao editar
  mantém a senha atual. O campo opcional "Lembrete de troca" destaca o
  item na lista quando a data se aproxima ou já passou.
- **Configuração** (só admin): mostra se a `VAULT_ENCRYPTION_KEY` está
  configurada e repete o aviso de backup separado — ver §3.1 e §6.

> Se a `VAULT_ENCRYPTION_KEY` não estiver configurada, a aba funciona
> normalmente para listar itens, mas criar, editar ou revelar mostra um
> aviso pedindo para configurar a chave (§3.1) antes de continuar.

### 5.2.6 Central do Cliente (só admin)

**Módulo de maior risco do sistema.** Cria contatos na Auvo com um link de
acesso **sem login e sem senha**, para o cliente ver os próprios chamados —
um erro vaza o painel de um cliente para outro. Usa um endpoint interno da
Auvo, não documentado, autenticado por **cookie de sessão do painel** (não
pela API oficial).

- **Nasce em simulação** — "executar" só registra o que seria criado, sem
  tocar a Auvo, até um admin desligar explicitamente em Configuração
  (mesmo checkbox de confirmação do modo produção da aba Chamados).
- **Fluxo em duas etapas**: "Preparar novo lote" monta a lista de clientes
  elegíveis (de-para OK com score de casamento acima do mínimo, ou
  marcados na mão por ID) e mostra a **pré-visualização** — nada é
  enviado ainda. Só depois de conferir a lista é que se marca quais
  entram e se clica em "Executar".
- **Fora de simulação**, executar pede o **cookie de sessão do painel**
  (copiado do navegador via F12) e o `auvo-user-request` a cada execução
  — nunca ficam salvos; são usados só naquela chamada e descartados
  depois.
- **Não duplica**: um cliente que já tem link criado não volta a aparecer
  como candidato num lote novo (uma tentativa que falhou pode ser
  retentada). Por isso ele some da pré-visualização — não é bug, é a
  idempotência funcionando. Para achar um cliente e confirmar que ele já
  foi processado (ou pra descobrir o ID de alguém que ainda não tem link,
  sem decorar o número), use a caixa **"Buscar cliente"** no topo da
  página — busca por nome, conta ou ID e mostra "já tem link" com atalho
  pro lote, em vez de simplesmente não aparecer em lugar nenhum.
- Cada lote fica no histórico com os itens (criado/erro/pendente) e pode
  ser exportado em xlsx — **documento sensível** (tem login/link de
  acesso), mesmo cuidado do Cofre de Senhas.
- **"Enviar no WhatsApp"**: cada contato criado com telefone válido (busca
  automática na API oficial da Auvo) ganha um botão que abre o WhatsApp
  numa aba nova, já com o contato certo e a mensagem pronta (template
  configurável). O envio é **assistido** — o site só monta a mensagem, um
  humano confere e clica em enviar dentro do próprio WhatsApp. Sem
  telefone válido, a linha mostra "sem telefone" em vez do botão.
- **"remover"** (na tela do lote, só em item `criado`): usar **só depois**
  de já ter apagado o contato manualmente no painel da Auvo (ex.: era um
  teste). Isso não mexe na Auvo — só avisa o Power Central que aquele
  registro não vale mais, e o cliente volta a poder ser processado de
  novo (aparece na busca e numa pré-visualização nova). O registro não é
  apagado, só marcado como "removido" — fica no histórico do lote.

> O formato do identificador, Login/Senha vazios e o
> `auvo-user-request` já foram **confirmados via F12** contra um contato
> de teste real (ver `docs/CENTRAL_CLIENTE.md` §6). Mesmo assim, na
> primeira execução em produção comece pequeno (1-2 clientes) e confira
> o resultado antes de rodar um lote maior — o formato exato da resposta
> da Auvo ainda não foi conferido byte a byte.

### 5.2.7 Minhas Tarefas

Aba **pessoal** (qualquer usuário logado, sem precisar ser admin) para
organizar o próprio trabalho em três blocos: **Dia**, **Semana** e
**Fixas**. Cada um só mostra as suas tarefas — ninguém vê ou mexe na
tarefa de outra pessoa.

- **Adicionar rápido**: digite o título no campo do topo de cada bloco e
  aperte Enter — não precisa abrir formulário nenhum. Detalhes extras
  (descrição, prioridade, data) se ajustam depois clicando no título da
  tarefa.
- **Atrasada não some**: uma tarefa do Dia ou da Semana que passou da
  data e continua pendente aparece destacada em vermelho, com a data
  original, dentro do próprio bloco atual — até você concluir, remarcar a
  data ou mover pra outro bloco.
- **Mover** ("→ Hoje" / "→ Semana" / "→ Fixa"): puxa a tarefa pra outro
  horizonte na hora — por exemplo, decidir que uma tarefa da Semana vai
  ser feita hoje.
- **Concluir**: clique no quadradinho ao lado da tarefa. As concluídas no
  dia ficam recolhidas no rodapé de cada bloco ("N concluída(s) hoje"),
  riscadas — clique de novo pra desmarcar se foi engano.
- Um cartão **"Suas tarefas de hoje"** aparece no Painel (dashboard)
  quando há pendência, com a contagem e quantas estão atrasadas — atalho
  direto pro bloco Dia sem precisar abrir a aba.

### 5.3 Administração

Em **Configurações** (só admin): janela de horas sem comunicação, lista de
códigos que comprovam comunicação (`TST, CLO, OPN` por padrão), intervalo
do coletor, limite do watchdog, cooldown do botão manual, retenção de
histórico, o **relatório periódico** (opcional, desligado por padrão:
envia a lista atual no Telegram no intervalo escolhido — ex.: de hora em
hora — mesmo sem mudança; os alertas por mudança continuam funcionando
independentemente), e a configuração do Telegram (com botão "Enviar
mensagem de teste" para confirmar que o bot está certo antes de depender
dele).

> Atenção: o relatório periódico e o ciclo automático de coleta dependem
> do agendador interno, que só roda no processo do serviço
> (`START_SCHEDULER=true` — o `install_service.ps1` configura isso). Com
> `flask run` "puro", nada roda sozinho: só o botão "Atualizar agora".

Em **Usuários**: criar, ativar/desativar e trocar senha de qualquer
usuário (não é possível desativar o próprio usuário logado).

Em **Auditoria**: histórico de login/logout, atualizações manuais, e
mudanças de configuração — com usuário, IP e data/hora, filtrável.

## 6. Backup

O banco de dados inteiro é **um único arquivo**:
`instance\power_central.db`. Fazer backup é copiar esse arquivo.

Sugestão simples: uma Tarefa Agendada do Windows (esta sim, sem problema
nenhum usar o Agendador — a restrição do prompt original era só sobre não
depender dele para o *coletor*, que já tem scheduler próprio) rodando 1x
por dia, copiando o arquivo para uma pasta de backup ou outro servidor:

```powershell
Copy-Item "C:\power_central\instance\power_central.db" `
  "D:\Backups\power_central\power_central_$(Get-Date -Format yyyyMMdd).db"
```

Pare o serviço antes de copiar se quiser garantir consistência total
(`Stop-Service PowerCentral`), embora o SQLite em modo normal já seja
razoavelmente seguro para cópia a quente.

## 7. Atualizando o sistema

```powershell
Stop-Service PowerCentral
cd C:\power_central
git pull
.venv\Scripts\pip install -r requirements.txt
$env:FLASK_APP = "app:create_app"
.venv\Scripts\python.exe -m flask db upgrade
Start-Service PowerCentral
```

## 8. Troubleshooting

**O painel não abre no navegador**
Confira `Get-Service PowerCentral` — se não está `Running`, veja os logs em
`logs\service_stderr.log` e `logs\power_central.log`. Erro comum: `.env`
faltando ou com `ENCRYPTION_KEY`/`SECRET_KEY` vazios.

**O serviço não inicia**
Rode manualmente para ver o erro na tela:
`\.venv\Scripts\waitress-serve.exe --call app:create_app` (dentro da pasta
do projeto, com as variáveis de ambiente do `.env` carregadas). Confira
também `logs\service_stderr.log`.

**Os dados não atualizam / o coletor parece parado**
Veja a página `/health` (ex.: `http://127.0.0.1:8000/health`) — mostra
`last_cycle_at` e `last_cycle_status`. Se `watchdog_alert_active: true`, o
sistema já devia ter avisado no Telegram. Confira se `START_SCHEDULER=true`
está definido no serviço (o `install_service.ps1` já configura isso
automaticamente).

**Não chegam alertas no Telegram**
Confirme em Configurações → Telegram que o status está "Configurado" e use
"Enviar mensagem de teste". Erros comuns: token errado, bot não foi
adicionado ao grupo, ou chat ID sem o sinal de menos (grupos costumam ter
ID negativo).

**Esqueci a senha do admin / preciso resetar**
Outro admin pode trocar pela tela Usuários. Se não existe nenhum admin
ativo, rode de novo `flask seed-admin` com um novo nome de usuário, ou
peça a um desenvolvedor para resetar a senha direto no banco.

**O painel mostra "o último ciclo terminou com erro"**
Normal quando o portal SoftGuard está fora do ar ou a sessão expirou — o
sistema tenta de novo automaticamente no próximo ciclo. Se persistir por
mais tempo que o limite do watchdog (15 min por padrão), chega um alerta no
Telegram; confira a mensagem de erro exibida no painel e, se for
credencial expirada, atualize `SOFTGUARD_PASSWORD` no `.env` e reinicie o
serviço.

**Onde ficam os logs**
`logs\power_central.log` (rotaciona automaticamente, não cresce sem
limite) e, se rodando como serviço, `logs\service_stdout.log` /
`logs\service_stderr.log`.

## 9. Checklist de aceite

Cada item abaixo foi validado por teste automatizado (suíte `pytest`,
rodar com `.venv\Scripts\pytest`) e/ou verificação manual:

| Critério | Como foi validado |
|---|---|
| Ciclo roda sozinho a cada 5 min e sobrevive a reinício da máquina | Scheduler interno (APScheduler) + serviço Windows com reinício automático (NSSM `AppExit Default Restart` + `SERVICE_AUTO_START`) |
| Conta com TST há 1h NÃO aparece como sem comunicação | `tests/unit/test_classification.py` |
| Conta com PTB há 1h APARECE como sem comunicação | `tests/unit/test_classification.py` |
| Telegram só recebe mensagem quando o conjunto muda; normalização gera aviso | `tests/integration/test_alerting.py`, `tests/integration/test_collector.py` |
| Dois cliques seguidos em "Atualizar agora" → segundo bloqueado com feedback | `tests/integration/test_manual_trigger.py`, `tests/integration/test_trigger_service.py` |
| Operador não acessa telas de admin; tentativa fica na auditoria | `tests/integration/test_rbac.py`, `tests/integration/test_admin_*.py` |
| Portal fora do ar → painel mostra erro, watchdog alerta, serviço continua vivo e se recupera | `tests/integration/test_collector.py::test_ciclo_com_erro_do_portal_registra_status_error_e_nao_derruba`, `tests/integration/test_watchdog_service.py` |
| Auditoria registra login, atualização manual e mudança de config com usuário e IP | `tests/integration/test_auth.py`, `tests/integration/test_manual_trigger.py`, `tests/integration/test_admin_settings.py` |
| Visual em claro/escuro, sem quebra em 1366px/1920px, estados vazio/erro desenhados | Verificação manual com screenshots (Playwright) em 1920px, 1366px e mobile, claro e escuro |

## 10. Fora de escopo (por enquanto)

Exposição direta na internet, app mobile, integração Auvo (abertura
automática de OS) e WhatsApp — ver `docs/ARQUITETURA.md` para os pontos de
extensão já preparados para essas fases futuras.
