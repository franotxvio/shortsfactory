# AGENTS.md — ShortsFactory

## Contexto

Este repositório implementa o projeto ShortsFactory, descrito em `shortsfactory_efficiency_v2_2.md`.

Objetivo do MVP: gerar 1 vídeo completo localmente antes de implementar upload no YouTube.

Fluxo do MVP:

ideia → roteiro → policy check → aprovação → TTS → legenda → assets → preview → aprovação → render final.

## Regras obrigatórias

- Não implementar upload no YouTube ainda.
- Não implementar multicanal ainda.
- Não implementar ContentBrain completo antes de existir analytics real.
- Não criar infraestrutura cloud ainda.
- Usar Docker Compose local.
- Usar Postgres com pgvector.
- Usar Redis local.
- Usar FastAPI no backend.
- Registrar custo em `cost_logs` desde a primeira chamada externa.
- Nenhuma chamada OpenAI sem cache quando aplicável.
- Nenhum render final sem preview aprovado.
- Nenhum TTS sem script aprovado.
- Nenhum asset sem licença/fonte registrada.
- Manter implementação incremental, testável e simples.

## Stack decidida

Backend:
- Python
- FastAPI
- SQLAlchemy async
- Alembic
- Pydantic Settings
- Pytest

Banco:
- PostgreSQL
- pgvector

Fila:
- Redis
- Celery

IA:
- GPT-4o-mini para roteiro, hook, policy e metadata
- text-embedding-3-small para SimilarityGuard
- OpenAI tts-1 para narração

Render:
- FFmpeg first
- Remotion só no futuro

Legenda:
- Whisper local

## Ordem de implementação

1. Bootstrap do backend
2. Docker Compose Postgres + Redis
3. Modelos e migrations
4. Cost logs
5. LLM cache
6. Script Engine
7. Policy Guard
8. SimilarityGuard
9. TTS Worker
10. Caption Worker
11. Asset Pool
12. Render Worker FFmpeg

## Proibições

- Não usar Selenium.
- Não postar nada automaticamente.
- Não adicionar Kubernetes.
- Não adicionar AWS.
- Não trocar providers da spec sem justificar.
- Não criar abstrações complexas antes do MVP local funcionar.

## Economia de tokens no Codex

- Antes de agir, leia `docs/codex-token-budget.md`.
- Nunca ler ou indexar `storage/`, `.venv/`, `node_modules/`, `dist/`, `build/` ou `.git/`.
- Não abrir arquivos grandes sem necessidade.
- Não resumir a spec inteira.
- Usar `shortsfactory_efficiency_v2_2.md` apenas quando o prompt pedir explicitamente.
- Preferir alterações pequenas e incrementais.
- Não alterar arquivos fora do escopo do prompt.
- Ao finalizar, responder com:
  - arquivos alterados;
  - testes executados;
  - próximos passos;
  - pendências.
