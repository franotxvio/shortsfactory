# Prompt 04 — TTS, Caption e Render Local

## Contexto obrigatório

Leia apenas:

- `AGENTS.md`
- `docs/codex-token-budget.md`
- `docs/spec-summary-for-codex.md`
- `docs/architecture.md`
- `apps/api/**`

Não leia:

- `storage/**`, exceto quando precisar salvar/ler arquivos gerados pelo próprio fluxo
- `.git/**`
- `.venv/**`
- `node_modules/**`
- arquivos fora do escopo
- `shortsfactory_efficiency_v2_2.md`, exceto se faltar detalhe técnico indispensável

## Tarefa

Implementar geração local do primeiro vídeo completo.

## Pode alterar

- `apps/api/**`
- `storage/**/.gitkeep`, se necessário
- scripts auxiliares em `scripts/**`, se necessário

## Não alterar

- `shortsfactory_efficiency_v2_2.md`
- `docker-compose.yml`
- `AGENTS.md`
- `docs/**`

## Implementar

- TTS Worker com OpenAI `tts-1`;
- bloqueio: só gerar TTS se script estiver aprovado;
- Caption Worker com Whisper local;
- Asset Pool local simples;
- Render Worker com FFmpeg;
- preview 720p;
- render final 1080x1920 só após preview aprovado;
- `cost_logs` para TTS;
- status do vídeo por etapa.

## Não implementar

- upload no YouTube;
- analytics;
- ContentBrain completo;
- dashboard avançado.

## Critérios de aceite

- gerar áudio a partir de script aprovado;
- gerar legenda com timestamps;
- selecionar asset local com licença registrada;
- renderizar preview;
- aprovar preview;
- renderizar final;
- arquivo final salvo em `storage/renders/finals`;
- resposta final lista arquivos alterados e comandos usados.
