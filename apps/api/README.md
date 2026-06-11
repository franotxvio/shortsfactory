# ShortsFactory API

Bootstrap inicial do backend FastAPI do ShortsFactory.

## Requisitos

- Python 3.11+
- Postgres local
- Redis local

## Configuração

O serviço lê variáveis de ambiente a partir de `.env` na raiz do repositório.
Use `.env.example` como base para montar esse arquivo localmente.

## Executar localmente

```bash
cd apps/api
python -m uvicorn app.main:app --reload
```

## Health check

```bash
curl http://127.0.0.1:8000/health
```

Resposta esperada:

```json
{"status":"ok"}
```

## Testes

```bash
cd apps/api
pytest
```

## Migrations

```bash
cd apps/api
python -m alembic upgrade head
```
