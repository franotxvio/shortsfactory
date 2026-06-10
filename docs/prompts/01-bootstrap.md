# Prompt 01 — Bootstrap ShortsFactory

## Contexto obrigatório

Leia apenas:

- `AGENTS.md`
- `docs/codex-token-budget.md`
- `docs/spec-summary-for-codex.md`
- `README.md`
- `.env.example`
- `docker-compose.yml`

Não leia `storage/`, `.git/`, `.venv/`, `node_modules/` ou arquivos fora do escopo.

## Tarefa

Criar bootstrap inicial do backend FastAPI em `apps/api`.

## Pode alterar

- `apps/api/**`
- arquivos de configuração Python necessários dentro de `apps/api`

## Não alterar

- `shortsfactory_efficiency_v2_2.md`
- `docker-compose.yml`
- `AGENTS.md`
- `storage/**`
- `docs/**`

## Implementar

- `pyproject.toml`
- app FastAPI
- endpoint `GET /health`
- settings via `.env`
- conexão async com Postgres
- conexão Redis
- pytest com teste de health
- `apps/api/README.md`

## Não implementar

- YouTube API
- Celery
- LLM
- TTS
- Render
- Dashboard
- Migrations complexas

## Critérios de aceite

- backend roda localmente
- `/health` retorna `{"status":"ok"}`
- teste de health passa
- resposta final lista arquivos alterados e comandos usados
