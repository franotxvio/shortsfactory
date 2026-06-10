# Prompt 03 — Script Engine, Cost Logs e Cache

## Contexto obrigatório

Leia apenas:

- `AGENTS.md`
- `docs/codex-token-budget.md`
- `docs/spec-summary-for-codex.md`
- `docs/architecture.md`
- `apps/api/**`

Não leia:

- `storage/**`
- `.git/**`
- `.venv/**`
- `node_modules/**`
- arquivos fora do escopo

## Tarefa

Implementar a primeira versão do Script Engine com cache e registro de custo.

## Pode alterar

- `apps/api/**`

## Não alterar

- `shortsfactory_efficiency_v2_2.md`
- `docker-compose.yml`
- `AGENTS.md`
- `storage/**`
- `docs/**`

## Implementar

- client OpenAI isolado;
- LLM cache antes de chamada externa;
- cost_logs para toda chamada OpenAI;
- geração de ideia;
- geração de hook;
- geração de roteiro;
- policy check simples;
- endpoints internos para criar script de teste;
- testes unitários dos serviços principais.

## Regras

- Usar GPT-4o-mini.
- Usar max_tokens conforme spec.
- Resposta da LLM deve ser JSON estruturado.
- Chamada repetida com mesmo input deve usar cache.
- Toda chamada externa deve registrar custo estimado.
- Não gerar TTS ainda.
- Não renderizar ainda.
- Não fazer upload.

## Critérios de aceite

- chamada repetida com mesmo input usa cache;
- `cost_logs` registra custo estimado;
- script gerado fica salvo no banco;
- policy check salva `risk_score`;
- testes passam.
