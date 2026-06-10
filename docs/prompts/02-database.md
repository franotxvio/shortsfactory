# Prompt 02 — Database Core

## Contexto obrigatório

Leia apenas:

- `AGENTS.md`
- `docs/codex-token-budget.md`
- `docs/spec-summary-for-codex.md`
- `docs/architecture.md`
- `apps/api/**`

Não leia:

- `storage/**`
- `.git/**`
- `.venv/**`
- `node_modules/**`
- arquivos fora do escopo
- `shortsfactory_efficiency_v2_2.md`, exceto se faltar detalhe técnico indispensável

## Tarefa

Implementar modelos SQLAlchemy async e migrations Alembic para as tabelas core do MVP.

## Pode alterar

- `apps/api/**`

## Não alterar

- `shortsfactory_efficiency_v2_2.md`
- `docker-compose.yml`
- `AGENTS.md`
- `docs/**`
- `storage/**`

## Criar

- `channels`
- `videos`
- `scripts`
- `cost_logs`
- `llm_cache`
- `asset_pool`
- `video_patterns`
- `weak_patterns`
- `winning_patterns`
- `content_embeddings`
- `similarity_checks`
- `cost_budget`

## Requisitos

- habilitar extensão `vector`;
- usar pgvector para `content_embeddings`;
- criar índices recomendados;
- criar enums/status simples;
- não implementar lógica de negócio ainda;
- migrations devem ser incrementais e testáveis.

## Critérios de aceite

- migration roda limpa;
- downgrade funciona se possível;
- testes básicos validam criação das tabelas;
- resposta final lista arquivos alterados e comandos usados.
