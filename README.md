# Power Central — Monitoramento de Comunicação de Alarmes

Sistema interno de monitoramento de comunicação de clientes de alarme
(Novo Millenium / PowerCentral). Arquitetura completa, modelo de dados e
plano de fases em [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md).

> Este README cobre **setup de desenvolvimento**. O manual de operação em
> PT-BR para a equipe de suporte (instalação como serviço Windows, backup,
> troubleshooting) é entregue na Fase 5.

## Status

- [x] Fase 0 — Fundação (config, modelos, migration inicial)
- [ ] Fase 1 — Domínio + cliente SoftGuard
- [ ] Fase 2 — Coletor, persistência e alertas Telegram
- [ ] Fase 3 — Web: autenticação + dashboard
- [ ] Fase 4 — Admin, atualização manual e auditoria
- [ ] Fase 5 — Hardening, deploy Windows e documentação

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

### Testes

```bash
pytest
```

## Estrutura

```
app/
  config.py, extensions.py, security.py, logging_config.py, cli.py
  models/        # SQLAlchemy — schema (users, settings, ciclos, contas, alertas, auditoria, watchdog)
  domain/        # regras de negócio puras (Fase 1)
  integrations/  # clientes SoftGuard/Telegram (Fase 1/2)
  services/      # orquestração: coletor, alertas, watchdog, auditoria (Fase 2+)
  web/           # blueprints Flask, templates, estáticos (Fase 3+)
migrations/      # Alembic (via Flask-Migrate)
tests/           # pytest — unit/, fixtures/
docs/            # arquitetura e (futuramente) manual de operação
```
