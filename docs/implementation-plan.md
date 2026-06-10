# ShortsFactory — Implementation Plan

## Fase 0 — Base

- Estrutura de pastas
- README
- AGENTS.md
- Docker Compose
- .env.example
- Prompts para Codex

## Fase 1 — Backend Base

- FastAPI
- Settings
- Healthcheck
- Postgres async
- Redis
- Pytest
- Alembic

## Fase 2 — Banco

- Models
- Migrations
- pgvector
- Índices
- Tabelas core

## Fase 3 — Script Engine

- LLM client
- Cache
- Cost logs
- Ideia
- Hook
- Roteiro
- Policy check

## Fase 4 — SimilarityGuard

- Embeddings
- content_embeddings
- similarity_checks
- cosine similarity
- bloqueios por threshold

## Fase 5 — Produção Local

- TTS
- Whisper local
- Asset pool
- FFmpeg preview
- FFmpeg final

## Fase 6 — Dashboard Básico

- Lista de vídeos
- Aprovar script
- Aprovar preview
- Ver status
- Ver custo

## Fase 7 — Upload e Analytics

Somente depois do MVP local funcionar.

- OAuth YouTube
- Upload idempotente
- Analytics windows
- ContentBrain real
