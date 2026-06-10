# ShortsFactory — Arquitetura Resumida

## Objetivo do MVP

Gerar 1 vídeo completo localmente antes de qualquer upload no YouTube.

Fluxo:

ideia → roteiro → policy check → aprovação → TTS → legenda → asset local → preview 720p → aprovação → render final 1080x1920

## Componentes

### API

- FastAPI
- Responsável por endpoints, status e orquestração leve
- Não executa processamento pesado

### Banco

- PostgreSQL local
- pgvector habilitado
- Armazena vídeos, scripts, custos, assets, embeddings e padrões

### Fila

- Redis local
- Celery em fase posterior
- Workers separados por responsabilidade

### Workers

- idea-worker
- script-worker
- policy-worker
- similarity-worker
- voice-worker
- caption-worker
- asset-worker
- render-worker

### IA

- GPT-4o-mini para ideia, hook, roteiro, policy e metadata
- text-embedding-3-small para SimilarityGuard
- OpenAI tts-1 para narração

### Render

- FFmpeg first
- Preview 720p antes do render final
- Render final apenas após aprovação humana

## Fora do MVP inicial

- YouTube API
- Analytics real
- ContentBrain completo
- Multicanal
- Escala
- Infra cloud
