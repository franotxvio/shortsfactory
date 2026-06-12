# ShortsFactory - operacao local do pipeline de video

Este guia descreve o estado atual do MVP local: como subir a infraestrutura, iniciar a API, o worker e o dashboard, e como executar o fluxo completo de um video fake ate o preparo de publicacao.

## Variaveis de ambiente

Use estas variaveis quando precisar sobrescrever o padrao local:

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

Comportamento importante:

- `fake` e o modo padrao do pipeline.
- OpenAI real e DeepSeek real so rodam quando explicitamente configurados.
- Upload real no YouTube ainda nao existe.
- `.mp4` como background asset continua bloqueado.
- `storage/` e saida de runtime e nao deve ser commitado.

## 1. Subir a infraestrutura

Suba Postgres e Redis com Docker Compose:

```bash
docker compose up -d
```

Portas locais padrao:

- Postgres no host: `127.0.0.1:5433`
- Postgres no container: `5432`
- Redis: `127.0.0.1:6379`

## 2. Rodar migrations

```bash
cd apps/api
python -m alembic upgrade head
```

## 3. Subir a API

```bash
cd apps/api
python -m uvicorn app.main:app --reload
```

A API sobe em `http://127.0.0.1:8000` por padrao.

## 4. Subir o worker

```bash
cd apps/api
python -m app.workers.video_jobs_worker
```

No Windows, o worker ja configura o event loop compativel antes de abrir conexoes async.

## 5. Subir o dashboard

```bash
cd apps/dashboard
npm run dev
```

Se necessario, ajuste:

```bash
$env:NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8000"
```

## 6. Demo local em 4 terminais

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

## 7. Fluxo completo no dashboard

O dashboard local expoe o pipeline inteiro para operar o MVP sem automatizacao externa.

Fluxo recomendado:

1. Criar video fake.
2. Editar o roteiro.
3. Selecionar ou enviar um asset local.
4. Escolher um template visual.
5. Produzir o pipeline.
6. Enfileirar em background, se quiser testar o worker.
7. Gerar export package.
8. Gerar YouTube prep.
9. Checar publish readiness.
10. Simular upload YouTube.

O painel tambem mostra:

- status e `stage_status`
- `audio_path`
- `caption_path`
- `asset_path`
- `preview_path`
- `final_path`
- `export_*` paths
- `youtube_publish_path`
- status do job em background
- checklist de publicacao
- status de autenticacao YouTube

## 8. Endpoints internos principais

### Criar video local de teste

`POST /internal/videos/test`

### Editar roteiro

`PATCH /internal/videos/{video_id}/script`

### Rodar TTS fake

`POST /internal/videos/{video_id}/tts`

### Gerar captions

`POST /internal/videos/{video_id}/captions`

### Selecionar asset

`POST /internal/videos/{video_id}/asset`

### Renderizar preview

`POST /internal/videos/{video_id}/preview`

### Aprovar preview

`POST /internal/videos/{video_id}/approve-preview`

### Renderizar final

`POST /internal/videos/{video_id}/final`

### Gerar export package

`POST /internal/videos/{video_id}/export-package`

### Gerar YouTube prep

`POST /internal/videos/{video_id}/youtube-prep`

### Checar readiness de publicacao

`GET /internal/videos/{video_id}/publish-readiness`

### Checar autenticacao YouTube

`GET /internal/videos/youtube/auth-status`

### Simular upload YouTube

`POST /internal/videos/{video_id}/youtube/upload`

### Consultar status do video

`GET /internal/videos/{video_id}/status`

## 9. Script manual via HTTP

Use o script local para executar o fluxo fake completo contra a API:

```bash
python scripts/manual_video_pipeline_http.py
```

Modo real controlado:

```bash
python scripts/manual_video_pipeline_http.py --mode real
```

O script imprime:

- `video_id`
- `stage_status` de cada etapa
- `audio_path`
- `caption_path`
- `asset_path`
- `preview_path`
- `final_path`

Regras do modo real:

- o padrao continua sendo fake
- `LLM_API_KEY` precisa existir para o provider de texto
- `OPENAI_API_KEY` continua separado para TTS real
- se a chave do provider de texto faltar, o fluxo falha com erro claro
- nada chama YouTube API real

## 10. YouTube Auth e upload

O estado atual prepara a autenticacao, mas nao publica de verdade.

Configurações relevantes:

- `YOUTUBE_CLIENT_SECRETS_PATH`
- `YOUTUBE_TOKEN_PATH`
- `YOUTUBE_UPLOAD_ENABLED`

Com `YOUTUBE_UPLOAD_ENABLED=false`, o upload fica bloqueado e o dashboard mostra `ready_but_disabled`.

O endpoint de upload atual e apenas um stub local:

- bloqueia quando a readiness nao esta pronta
- bloqueia quando a autenticacao nao esta pronta
- retorna `simulated` somente quando tudo esta configurado
- nao faz chamada real ao YouTube

## 11. Assets e export

Regras atuais do storage:

- `storage/` e apenas saida local
- nao deve ser commitado
- assets de fundo `.mp4` continuam bloqueados
- `youtube_publish.json` e salvo dentro do pacote de export

## 12. Reset local de demo

Limpar arquivos gerados:

```bash
python scripts/cleanup_demo_storage.py
```

Limpar videos demo/local do banco:

```bash
POST /internal/videos/demo/reset
```

Body:

```json
{
  "confirm": true
}
```

Regras:

- somente fora de `production`
- exige `confirm=true`
- remove videos demo/local dos canais `internal-test` e `manual-test`

