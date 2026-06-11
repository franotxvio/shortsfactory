# ShortsFactory - Operacao local do pipeline de video

Este guia cobre a execucao local do backend e do fluxo manual de producao de video via endpoints internos.

## 1. Subir Postgres e Redis

Use o `docker compose` do projeto para subir os servicos locais de banco e fila.

```bash
docker compose up -d postgres redis
```

Se os nomes dos servicos forem diferentes no seu ambiente, use os nomes definidos no `docker-compose.yml`.

O Postgres local desta configuracao usa:

- host: `127.0.0.1`
- porta no host: `5433`
- porta no container: `5432`

## 2. Rodar migrations

Execute as migrations do backend a partir de `apps/api`.

```bash
cd apps/api
python -m alembic upgrade head
```

## 3. Subir a API

Suba a API FastAPI local em modo de desenvolvimento.

```bash
cd apps/api
python -m uvicorn app.main:app --reload
```

Por padrao, a API fica em `http://127.0.0.1:8000`.

## 4. Endpoints internos de video em modo fake

Todos os exemplos abaixo usam `execution_mode: fake` para evitar chamada real a OpenAI e evitar dependencia de Whisper real.

### Criar video local de teste

`POST /internal/videos/test`

```json
{
  "topic": "Como aprender Python",
  "channel_slug": "manual-test",
  "channel_name": "Manual Test",
  "video_title": "Teste manual",
  "execution_mode": "fake"
}
```

### Rodar TTS fake

`POST /internal/videos/{video_id}/tts`

```json
{
  "execution_mode": "fake"
}
```

### Gerar captions

`POST /internal/videos/{video_id}/captions`

```json
{
  "execution_mode": "fake"
}
```

### Selecionar ou criar asset local

`POST /internal/videos/{video_id}/asset`

### Renderizar preview

`POST /internal/videos/{video_id}/preview`

### Aprovar preview

`POST /internal/videos/{video_id}/approve-preview`

### Renderizar final

`POST /internal/videos/{video_id}/final`

### Consultar status do video

`GET /internal/videos/{video_id}/status`

## 5. Script manual via HTTP

Execute o script local para percorrer o fluxo completo em modo fake:

```bash
python scripts/manual_video_pipeline_http.py
```

O script executa:

1. health check
2. criacao do video local
3. TTS fake
4. captions
5. asset local
6. preview
7. aprovacao do preview
8. render final
9. consulta de status final

Ele imprime:

- `video_id`
- `stage_status` de cada etapa
- `audio_path`
- `caption_path`
- `asset_path`
- `preview_path`
- `final_path`

Para validar OpenAI de forma controlada com custo baixo:

```bash
$env:OPENAI_API_KEY="sk-..."
python scripts/manual_video_pipeline_http.py --mode real
```

O modo `real`:

- nao muda o padrao `fake`
- falha com erro claro se `LLM_API_KEY` nao estiver configurada para o Script Engine
- continua exigindo `OPENAI_API_KEY` apenas se voce for seguir para TTS real
- registra `cost_logs` quando usa provider real no Script Engine

### Configuracao de LLM

Use estas variaveis para o Script Engine:

OpenAI:

```bash
LLM_PROVIDER=openai
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
```

DeepSeek:

```bash
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

Diferença importante:

- `LLM_PROVIDER` e `LLM_API_KEY` controlam apenas texto/JSON do Script Engine
- `OPENAI_API_KEY` continua sendo usada para TTS
- DeepSeek cobre geração de texto, nao narração

## 6. Observacoes

- O fluxo manual nao chama OpenAI real por padrao.
- O fluxo manual nao depende de Whisper real.
- O render final continua bloqueado ate o preview ser aprovado.
- O `script_id` e o `script_status` sao preservados nos retornos das etapas quando o video possui script associado.
