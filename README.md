# Power Central — Monitoramento de Comunicação de Alarmes

Sistema interno de monitoramento de comunicação de clientes de alarme
(Novo Millenium / PowerCentral).

- Arquitetura, modelo de dados e plano de fases: [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md)
- Instalação, operação do dia a dia e troubleshooting (PT-BR, para a
  equipe de suporte): [`docs/OPERACAO.md`](docs/OPERACAO.md)

> Este README cobre **setup de desenvolvimento**. Para instalar em
> produção (serviço Windows, HTTPS interno, backup), use o manual de
> operação acima.

## Status

- [x] Fase 0 — Fundação (config, modelos, migration inicial)
- [x] Fase 1 — Domínio + cliente SoftGuard
- [x] Fase 2 — Coletor, persistência e alertas Telegram
- [x] Fase 3 — Web: autenticação + dashboard
- [x] Fase 4 — Admin, atualização manual e auditoria
- [x] Fase 5 — Hardening, deploy Windows e documentação

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
flask db upgrade                     # cria o schema em instance/power_central.db
flask seed-admin                     # cria o primeiro usuário administrador
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
  models/        # SQLAlchemy — schema (users, settings, ciclos, contas, alertas, auditoria, watchdog)
  domain/        # regras de negócio puras: classificação, datas, diff de estado, ordenação, formatação
  integrations/  # clientes SoftGuard/Telegram (+ stub documentado para Auvo, fase futura)
  services/      # orquestração: coletor, alertas, watchdog, settings, auditoria, retenção, trigger manual
  web/           # blueprints Flask (auth, dashboard, admin), templates, estáticos
migrations/      # Alembic (via Flask-Migrate)
tests/           # pytest — unit/ e integration/
scripts/         # instalação como serviço Windows (NSSM) + exemplo de Caddyfile
docs/            # ARQUITETURA.md (design) e OPERACAO.md (manual PT-BR)
```
