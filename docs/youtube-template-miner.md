# YouTube Template Miner

Este miner coleta apenas metadados públicos do YouTube Data API para estudar padrões de Shorts.

Ele não:
- baixa vídeos;
- baixa áudio;
- usa `yt-dlp`;
- reutiliza mídia do YouTube como asset;
- publica vídeos;
- chama OpenAI ou DeepSeek.

O objetivo é aprender estrutura, hook, ritmo e formatos recorrentes para inspirar roteiros e layouts originais no ShortsFactory.

## Como rodar

Defina a chave:

```bash
set YOUTUBE_DATA_API_KEY=...
```

Execute:

```bash
python scripts/collect_youtube_template_patterns.py --help
python scripts/collect_youtube_template_patterns.py
```

Saída padrão:
- JSON em `apps/api/storage/config/trends/youtube_template_patterns/{date}/youtube_template_patterns.json`
- resumo em `apps/api/storage/config/trends/youtube_template_patterns/{date}/youtube_template_patterns_summary.md`

## Regra de uso

Os Shorts gerados pelo ShortsFactory devem continuar originais:
- scripts próprios
- assets próprios
- layouts próprios
- sem copiar clipes, áudio ou cenas de referência
