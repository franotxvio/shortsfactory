# Prompt 00 — Environment Check

## Objetivo

Validar que o ambiente local do ShortsFactory está pronto antes de iniciar implementação.

## Comandos obrigatórios

docker compose up -d
docker ps
docker exec -it shortsfactory-redis redis-cli ping
docker exec -it shortsfactory-postgres psql -U shortsfactory -d shortsfactory -c "SELECT extname FROM pg_extension WHERE extname = 'vector';"

## Resultado esperado

Redis:

PONG

Postgres:

vector

## Critério de aceite

- Container `shortsfactory-redis` está rodando.
- Container `shortsfactory-postgres` está rodando.
- Redis responde `PONG`.
- PostgreSQL tem extensão `vector` ativa.
- Se qualquer etapa falhar, não iniciar Prompt 01.
