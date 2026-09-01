# Power Central

Plataforma interna de suporte da **Novo Millenium**: nasceu como
monitoramento de comunicação de contas de alarme (contra o portal
SoftGuard) e cresceu para reunir os relatórios, integrações e
ferramentas do dia a dia da equipe num único site — o que antes era
feito manualmente (puxar dado de portal, montar planilha, lembrar de
checar) hoje é gerado, monitorado e alertado pelo próprio sistema.

- Arquitetura, camadas e modelo de dados: [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md)
- Instalação, operação do dia a dia e troubleshooting (PT-BR, para a
  equipe de suporte): [`docs/OPERACAO.md`](docs/OPERACAO.md)

> Este README cobre **setup de desenvolvimento**. Para instalar em
> produção (serviço Windows, HTTPS interno, backup), use o manual de
> operação acima.

## Módulos

Cada módulo tem seu próprio documento de design (camadas, decisões,
regras confirmadas em produção) — link na tabela. Visão geral de uso
para cada um está em `docs/OPERACAO.md` §5.

| Módulo | O que faz | Design |
|---|---|---|
| **Painel de comunicação** | Monitora contas de alarme contra o portal SoftGuard a cada 5 min; mostra quem está sem comunicação real, alerta automático no Telegram quando o conjunto muda | [`ARQUITETURA.md`](docs/ARQUITETURA.md) |
| **Relatórios — Atendimentos** | Gera o relatório de atendimentos de um período (dia inteiro), com aba de eventos descartados e o motivo | [`RELATORIOS.md`](docs/RELATORIOS.md) |
| **Relatórios — Disparos** | Relatório de disparos "puros" com janela móvel (desde o último relatório), tempo de conclusão e tempo pra ligar pro cliente calculados automaticamente | [`RELATORIOS.md`](docs/RELATORIOS.md) |
| **Disparos Geral** | Fechamento de fim de semana: classifica **todos** os disparos (após arme / seguido de desarme / aleatório), 3 abas por grupo de loja, abre chamado na Auvo acima de um limite | [`RELATORIO_TECNICO.md`](docs/RELATORIO_TECNICO.md) |
| **Chamados (Auvo)** | Abre chamado na Auvo automaticamente por gatilho (sem comunicação / disparos), com de-para de conta, cooldown e simulação por padrão | [`CHAMADOS_AUVO.md`](docs/CHAMADOS_AUVO.md) |
| **Relatório do Técnico** | Gera o relatório de atendimento por loja/dia a partir da agenda da Auvo, um arquivo por loja, com override manual e zip | [`RELATORIO_TECNICO.md`](docs/RELATORIO_TECNICO.md) |
| **Eficácia do Técnico (BI)** | Cruza ordens da Auvo com disparos pra medir se a visita realmente resolveu o problema — dashboard com gráficos e tabelas exportáveis | [`BI_EFICACIA_TECNICO.md`](docs/BI_EFICACIA_TECNICO.md) |
| **Cofre de Senhas** | Credenciais de sistemas da empresa (câmera, roteador, plataformas) cifradas em repouso, por papel, com reautenticação pra revelar | [`COFRE_SENHAS.md`](docs/COFRE_SENHAS.md) |
| **Central do Cliente** | Cria link de acesso sem login/senha pro portal do cliente na Auvo (endpoint interno, cookie de sessão) — admin-only, simulação por padrão, cada telefone cadastrado vira um botão de WhatsApp assistido | [`CENTRAL_CLIENTE.md`](docs/CENTRAL_CLIENTE.md) |
| **Minhas Tarefas** | Tarefas pessoais do usuário logado em três horizontes (Dia/Semana/Fixas); atrasada não some, fica marcada até decisão humana | [`TAREFAS.md`](docs/TAREFAS.md) |
| **Bot do Técnico (Telegram)** | O técnico pede pelo Telegram e recebe na hora o histórico de eventos ou o zoneamento da conta; lista fechada de IDs autorizados, cooldown e auditoria de cada pedido | [`BOT_TECNICO.md`](docs/BOT_TECNICO.md) |

## Status

Todas as fases abaixo estão concluídas e cobertas por teste; ver a
tabela "Fases" no fim de cada `docs/<MODULO>.md` para o detalhe de cada
entrega.

- [x] Fundação — config, modelos, migration inicial, coletor + painel de comunicação
- [x] Relatórios — Atendimentos e Disparos (Aleatórios)
- [x] Chamados (Auvo) — abertura automática + Disparos Geral
- [x] Relatório do Técnico
- [x] Eficácia do Técnico (BI)
- [x] Cofre de Senhas
- [x] Central do Cliente (links de acesso + WhatsApp assistido)
- [x] Minhas Tarefas

## Setup local

Requer Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

cp .env.example .env                # preencha os valores reais, nunca commite este arquivo
```

### Banco de dados

```bash
export FLASK_APP=app:create_app      # Windows (PowerShell): $env:FLASK_APP="app:create_app"
flask db upgrade                     # cria/atualiza o schema em instance/power_central.db
flask seed-admin                     # cria o primeiro usuário administrador
flask generate-key                   # gera uma chave Fernet pra ENCRYPTION_KEY/VAULT_ENCRYPTION_KEY (.env)
```

### Rodando localmente

```bash
flask run                            # servidor de desenvolvimento
flask collect --dry-run              # roda um ciclo do coletor com dados de exemplo
```

Em produção, o processo é `waitress-serve --call app:create_app` com
`START_SCHEDULER=true` — ver `docs/OPERACAO.md` seção 4 e `scripts/install_service.ps1`.

### Testes

```bash
pytest
```

## Estrutura

```
app/
  config.py, extensions.py, security.py, logging_config.py, cli.py, scheduler.py
  models/        # SQLAlchemy — schema puro (users, settings, ciclos/contas, auditoria,
                 # watchdog, relatórios, auvo, técnico, bi, cofre, central do cliente, tarefas)
  domain/        # regras de negócio puras, sem I/O: classificação, datas, diff de estado,
                 # atendimentos, disparos (aleatório e geral), técnico, bi, cofre,
                 # central do cliente, tarefas
  integrations/  # clientes HTTP: SoftGuard, Telegram, Auvo (API oficial + endpoint
                 # interno do painel, isolado)
  services/      # orquestração: coletor, alertas, watchdog, relatórios, auvo,
                 # técnico, bi, cofre, central do cliente, tarefas, auditoria, retenção
  web/           # blueprints Flask (auth, dashboard, admin, reports, auvo, tecnico,
                 # bi, cofre, central_cliente, tarefas), templates, estáticos
migrations/      # Alembic (via Flask-Migrate)
tests/           # pytest — unit/ e integration/ (500+ testes)
scripts/         # instalação como serviço Windows (NSSM), exemplos de Caddyfile e
                 # Cloudflare Tunnel, scripts de debug pontuais
docs/            # ARQUITETURA.md (design) + OPERACAO.md (manual PT-BR) +
                 # um documento de design por módulo (RELATORIOS, CHAMADOS_AUVO,
                 # RELATORIO_TECNICO, BI_EFICACIA_TECNICO, COFRE_SENHAS,
                 # CENTRAL_CLIENTE, TAREFAS)
```
