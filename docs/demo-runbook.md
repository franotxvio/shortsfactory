# ShortsFactory - Demo Local Runbook

Roteiro curto para demonstrar o MVP local do ShortsFactory sem chamar serviços reais.

## 1. Pre-requisitos

- Docker Desktop ou Docker Engine em execucao
- Python instalado para rodar a API e o smoke
- Node.js instalado para rodar o dashboard
- Repo clonado em `D:\Workspace\Projetos\ShortsFactory`

## 2. Subir Docker, Postgres e Redis

No Git Bash:

```bash
cd /d/Workspace/Projetos/ShortsFactory
docker compose up -d
```

Portas locais esperadas:

- Postgres: `127.0.0.1:5433`
- Redis: `127.0.0.1:6379`

## 3. Subir a API

```bash
cd /d/Workspace/Projetos/ShortsFactory/apps/api
python -m uvicorn app.main:app --reload
```

API local:

- `http://127.0.0.1:8000`

## 4. Subir o worker

```bash
cd /d/Workspace/Projetos/ShortsFactory/apps/api
python -m app.workers.video_jobs_worker
```

## 5. Subir o dashboard

```bash
cd /d/Workspace/Projetos/ShortsFactory/apps/dashboard
npm run dev
```

Abra:

- `http://localhost:3000`

## 6. Rodar o smoke local

```bash
cd /d/Workspace/Projetos/ShortsFactory
python scripts/smoke_demo_local.py --base-url http://127.0.0.1:8000
```

## 7. Demonstração pelo dashboard

Fluxo sugerido:

1. Criar video fake.
2. Revisar e editar roteiro.
3. Selecionar asset local.
4. Escolher template visual.
5. Rodar TTS.
6. Gerar captions.
7. Gerar preview.
8. Aprovar preview.
9. Gerar render final.
10. Gerar export package.
11. Gerar YouTube prep.
12. Checar publish readiness.
13. Simular upload do YouTube.

## 8. Como confirmar que nao houve upload real

Verifique:

- `YOUTUBE_UPLOAD_ENABLED=false`
- a resposta do stub mostra `upload_status=ready_but_disabled`
- nenhum fluxo chama a API real do YouTube

Se quiser conferir a configuracao:

```bash
echo $YOUTUBE_UPLOAD_ENABLED
```

## 9. Limpar storage local antes de commit

No Git Bash:

```bash
cd /d/Workspace/Projetos/ShortsFactory
rm -rf apps/api/storage
```

No PowerShell:

```powershell
Remove-Item -LiteralPath .\apps\api\storage -Recurse -Force
```

## 10. Checklist final da demo

- [ ] Docker/Postgres/Redis estao no ar
- [ ] API responde em `http://127.0.0.1:8000/health`
- [ ] Worker iniciou sem erro
- [ ] Dashboard abre em `http://localhost:3000`
- [ ] Video fake foi criado
- [ ] Roteiro foi revisado
- [ ] Asset e template foram escolhidos
- [ ] Preview foi gerado
- [ ] Preview foi aprovado
- [ ] Render final foi gerado
- [ ] Export package foi gerado
- [ ] YouTube prep foi gerado
- [ ] Publish readiness foi checado
- [ ] Upload stub retornou `ready_but_disabled` ou `blocked` de forma segura
- [ ] `apps/api/storage` foi limpo antes do commit

