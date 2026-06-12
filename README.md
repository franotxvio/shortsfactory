# ShortsFactory

ShortsFactory is a local-first pipeline for creating one complete YouTube Shorts video before any real upload automation exists.

## MVP goal

Generate one full video locally:

idea -> script -> policy check -> approval -> TTS -> captions -> local asset -> preview 720p -> preview approval -> final render 1080x1920

## What is in scope

- FastAPI backend
- PostgreSQL + pgvector
- Redis + worker queue
- Local dashboard
- Local file storage
- Fake mode by default
- Controlled real mode only when explicitly configured

## What is not in scope yet

- Real YouTube upload
- OAuth flow for YouTube
- Full multi-channel automation
- Full ContentBrain/analytics loop
- Cloud infrastructure

## Core local flow

1. Start infrastructure.
2. Run migrations.
3. Start the API.
4. Start the worker.
5. Start the dashboard.
6. Create a fake video.
7. Edit the script if needed.
8. Choose an asset and a visual template.
9. Produce the pipeline, sync or background.
10. Generate the export package.
11. Generate YouTube prep.
12. Check publish readiness.
13. Simulate a YouTube upload.

## Environment variables

Required or useful local variables:

- `DATABASE_URL`
- `REDIS_URL`
- `LLM_PROVIDER`
- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL`
- `OPENAI_API_KEY`
- `YOUTUBE_CLIENT_SECRETS_PATH`
- `YOUTUBE_TOKEN_PATH`
- `YOUTUBE_UPLOAD_ENABLED`
- `NEXT_PUBLIC_API_BASE_URL`

Notes:

- `fake` mode is the default for the pipeline.
- Real OpenAI/DeepSeek text generation only runs when explicitly configured.
- Real YouTube upload does not exist yet.
- `storage/` is runtime output and should not be committed.
- `.mp4` background assets are still blocked.

## Local demo in 4 terminals

1. Infra:

```bash
docker compose up -d
```

2. API:

```bash
cd apps/api
python -m uvicorn app.main:app --reload
```

3. Worker:

```bash
cd apps/api
python -m app.workers.video_jobs_worker
```

4. Dashboard:

```bash
cd apps/dashboard
npm run dev
```

## Useful commands

Run migrations:

```bash
cd apps/api
python -m alembic upgrade head
```

Run the manual HTTP pipeline script:

```bash
python scripts/manual_video_pipeline_http.py
```

Fake is the default. Real mode is only allowed when the relevant keys are present and the request explicitly asks for it.

## Documentation

- `docs/operational-video-pipeline.md`
- `docs/architecture.md`
- `docs/spec-summary-for-codex.md`
- `docs/milestones.md`
- `docs/prompts/`
