# ShortsFactory

Plataforma automatizada para criação, renderização, aprovação e futura publicação de vídeos YouTube Shorts com foco em custo mínimo, performance máxima e aprendizado por dados.

## Objetivo do MVP

Gerar 1 vídeo completo localmente:

ideia → roteiro → policy check → aprovação → TTS → legenda → asset local → preview 720p → aprovação → render final 1080x1920

## Fora do escopo inicial

- Upload automático no YouTube
- Analytics real
- ContentBrain completo
- Multicanal
- Escala
- Monetização

## Stack MVP

- Backend: FastAPI
- Banco: PostgreSQL local
- Fila: Redis + Celery
- LLM: OpenAI GPT-4o-mini
- TTS: OpenAI tts-1
- Embeddings: text-embedding-3-small
- Similaridade: PostgreSQL + pgvector
- Legenda: Whisper local
- Render: FFmpeg
- Storage: local no MVP, R2 depois

## Documentação principal

- `shortsfactory_efficiency_v2_2.md`: spec técnica fechada
- `AGENTS.md`: instruções para IA/coding agents
- `docs/milestones.md`: roadmap de implementação
- `docs/prompts/`: prompts prontos para Codex/Claude
