# Codex Token Budget — ShortsFactory

Nunca peça para o Codex ler o projeto inteiro sem necessidade.

## Regras

- Leia somente arquivos explicitamente citados no prompt.
- Não leia `storage/`, `.venv/`, `node_modules/`, `.git/`, `dist/`, `build/`.
- Não altere arquivos fora do escopo.
- Faça mudanças pequenas e testáveis.
- Prefira modelo econômico para tarefas locais.
- Use modelo forte só para bugs difíceis, arquitetura ou refactors multi-arquivo.
- Ao final, liste arquivos alterados, testes executados e pendências.

## Formato obrigatório de prompt

Leia apenas:
- `AGENTS.md`
- `docs/codex-token-budget.md`
- arquivos específicos da tarefa

Pode alterar:
- arquivos/pastas específicos

Não alterar:
- tudo fora do escopo

Critérios de aceite:
- testes/comandos claros
