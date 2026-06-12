# YouTube Trend Miner

Script local para coletar referencias publicas de tendencias do YouTube usando apenas API key.

## O que ele faz

- usa `videos.list` com `chart=mostPopular` quando nenhum `--query` e informado
- usa `search.list` + `videos.list` quando `--query` e informado
- coleta `snippet`, `statistics` e `contentDetails`
- calcula `age_hours`, `views_per_hour`, `engagement_rate` e `is_short_candidate`
- salva um JSON local ordenado por `views_per_hour`

## O que ele nao faz

- nao usa OAuth
- nao publica nada
- nao baixa videos
- nao copia conteudo
- nao chama OpenAI
- nao chama DeepSeek

## Configuracao

Defina a API key no ambiente:

```bash
export YOUTUBE_DATA_API_KEY="sua-chave-aqui"
```

No PowerShell:

```powershell
$env:YOUTUBE_DATA_API_KEY="sua-chave-aqui"
```

## Como rodar no Git Bash

```bash
cd /d/Workspace/Projetos/ShortsFactory
python scripts/collect_youtube_trends.py --region-code BR --max-results 50 --output apps/api/storage/config/trends/youtube_trends.json
```

Com busca por termo:

```bash
python scripts/collect_youtube_trends.py --query "python shorts" --published-after 2026-01-01T00:00:00Z
```

Se `YOUTUBE_DATA_API_KEY` nao estiver configurada, o script falha com erro claro.
