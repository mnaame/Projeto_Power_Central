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
reinício automático em caso de falha, e já inicia o serviço.

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
