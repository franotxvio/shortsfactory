# ShortsFactory — Spec Summary for Codex

## MVP

Gerar 1 vídeo completo localmente:

ideia → roteiro → policy check → aprovação → TTS → legenda → asset local → preview 720p → aprovação → render final 1080x1920

## Fora do MVP

- YouTube API
- Analytics real
- ContentBrain completo
- Multicanal
- Escala
- Infra cloud

## Stack

- Backend: FastAPI
- DB: PostgreSQL + pgvector
- Cache/Fila: Redis
- ORM: SQLAlchemy async
- Migrations: Alembic
- Tests: Pytest
- LLM: GPT-4o-mini
- Embeddings: text-embedding-3-small
- TTS: OpenAI tts-1
- Caption: Whisper local
- Render: FFmpeg first

## Gates obrigatórios

- Sem chamada OpenAI sem cache quando aplicável.
- Sem TTS antes de `SCRIPT_APPROVED`.
- Sem render final antes de `RENDER_PREVIEW_APPROVED`.
- Sem upload no YouTube no MVP.
- Todo custo externo deve registrar `cost_logs`.
- Todo asset deve ter fonte/licença.

## Custos alvo

- Custo por vídeo MVP: < $0.40
- Alerta: custo/vídeo > $0.50
- Hard review: custo/vídeo > $0.60 por 3 vídeos seguidos

## Tabelas core

- channels
- videos
- scripts
- cost_logs
- llm_cache
- asset_pool
- video_patterns
- weak_patterns
- winning_patterns
- content_embeddings
- similarity_checks
- cost_budget

## SimilarityGuard

- Provider: OpenAI `text-embedding-3-small`
- Storage: PostgreSQL + pgvector
- Similaridade: cosine similarity
- Cache por `content_hash`
- Não usar modelo local no MVP

## ContentBrain

- Não implementar completo antes de analytics real.
- V1 é determinístico.
- GPT só para relatório qualitativo futuro.
