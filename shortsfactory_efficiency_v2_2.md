# ShortsFactory — Documentação Técnica v2.2
### Edição Eficiência: Arquitetura de Custo Mínimo, Performance Máxima e SimilarityGuard Fechado

**Autor:** Otávio Juliano
**Versão:** 2.2 — Efficiency Edition
**Data:** 2026-06-10
**Status:** Spec de Implementação
**Meta:** custo < $0.40 por vídeo publicado
**Mudança v2.2:** decisão fechada de embeddings para SimilarityGuard

---

## Sumário

1. [Filosofia de Eficiência](#1-filosofia-de-eficiência)
2. [Stack Definitiva com Justificativa de Custo](#2-stack-definitiva-com-justificativa-de-custo)
3. [Arquitetura Eficiente](#3-arquitetura-eficiente)
4. [Sistema de Cache — Redução de Custo de LLM](#4-sistema-de-cache--redução-de-custo-de-llm)
5. [Asset Engine com Pool Próprio](#5-asset-engine-com-pool-próprio)
6. [ContentBrain — Lógica Concreta de Aprendizado](#6-contentbrain--lógica-concreta-de-aprendizado)
7. [Modelo de Dados — Adições para Eficiência](#7-modelo-de-dados--adições-para-eficiência)
8. [Providers — Decisões Fechadas](#8-providers--decisões-fechadas)
9. [Geração de Legendas com Whisper Local](#9-geração-de-legendas-com-whisper-local)
10. [Render Engine — FFmpeg First](#10-render-engine--ffmpeg-first)
11. [Idempotência e Safety Gates](#11-idempotência-e-safety-gates)
12. [SimilarityGuard — Controle de Conteúdo Repetitivo](#12-similarityguard--controle-de-conteúdo-repetitivo)
13. [Observabilidade de Custo em Tempo Real](#13-observabilidade-de-custo-em-tempo-real)
14. [Roadmap com Foco em Eficiência](#14-roadmap-com-foco-em-eficiência)
15. [Definição de Pronto — Versão Eficiente](#15-definição-de-pronto--versão-eficiente)
16. [Riscos de Eficiência e Mitigações](#16-riscos-de-eficiência-e-mitigações)

---

## 1. Filosofia de Eficiência

Esta versão da documentação parte de um princípio diferente da V1: toda decisão técnica deve ser justificada pelo seu custo-benefício real. Nenhuma tecnologia entra na stack por ser "melhor em geral" — entra se for a mais barata para o job.

### 1.1 A Equação Central

```
Eficiência = (Views × Retenção) / (Custo Total + Tempo de Produção)
```

O sistema deve maximizar o numerador e minimizar o denominador. Isso guia cada decisão de arquitetura.

### 1.2 Princípios Inegociáveis

- Nenhuma chamada de LLM sem checar cache primeiro
- Nenhum render sem aprovação humana do preview
- Nenhum asset gerado ou comprado se já existe no pool
- Nenhuma infra provisionada antes de provar necessidade
- Custo-alvo por vídeo: abaixo de $0.40 no MVP
- Todo job tem custo registrado — sem exceção

### 1.3 O Que Não Fazer

| Anti-padrão | Custo Real | Decisão Correta |
|---|---|---|
| Chamar GPT-4o para cada roteiro | ~$0.15/roteiro | GPT-4o-mini com prompt otimizado |
| ElevenLabs em plano pago alto | ~$0.18/min áudio | OpenAI TTS a $0.015/1k chars |
| Remotion com server dedicado | ~$80/mês idle | Worker local + render sob demanda |
| Pexels API por vídeo | N chamadas/vídeo | Pool próprio com download batch |
| Redis Cloud pago desde o MVP | ~$30/mês | Redis local no mesmo VPS |
| PostgreSQL gerenciado desde o início | ~$50/mês | Postgres local com backup automático |

---

## 2. Stack Definitiva com Justificativa de Custo

### 2.1 Decisões Fechadas — Sem Alternativas em Aberto

| Camada | Tecnologia | Custo | Motivo |
|---|---|---|---|
| Backend | FastAPI (Python) | Grátis | Ecossistema IA nativo, async, rápido |
| Frontend | Next.js + Tailwind | Grátis | Dashboard simples, não precisa de mais |
| Banco | PostgreSQL local | Grátis | Gerenciado só na fase 4+ |
| Fila | Redis local + Celery | Grátis | Suficiente para MVP e fase 2 |
| LLM Roteiro | GPT-4o-mini | ~$0.04/roteiro | Qualidade suficiente, 10x mais barato |
| Embeddings | OpenAI `text-embedding-3-small` | ~$0.02/1M tokens | SimilarityGuard barato, simples e sem setup local complexo no MVP |
| ContentBrain V1 | Regras determinísticas + GPT-4o opcional para relatório | $0.00–$0.02/análise | Decisão automática por regra; GPT só interpreta e sugere hipóteses |
| TTS | OpenAI TTS (tts-1) | ~$0.015/1k chars | Melhor custo-qualidade disponível |
| Render | FFmpeg puro | Grátis | Remotion só para templates complexos |
| Assets Visuais | Pool próprio (Pexels batch) | Grátis após download | Download único, reuso infinito |
| Storage | Cloudflare R2 | $0.015/GB/mês | Zero egress, 10GB free tier |
| Deploy | Hetzner VPS (8 vCPU/16GB) | ~$25/mês | Metade do preço da AWS equivalente |
| Monitoramento | Sentry free + logs JSON | Grátis | Suficiente para MVP |

### 2.2 Custo Estimado por Vídeo (MVP)

| Componente | Custo Estimado | Base de Cálculo |
|---|---|---|
| LLM — Ideia + Hook + Roteiro | $0.040 | GPT-4o-mini, ~3k tokens/vídeo |
| LLM — Retention Optimizer | $0.010 | GPT-4o-mini, ~1k tokens |
| Embedding — SimilarityGuard | ~$0.00002 | `text-embedding-3-small`, ~800–1.000 tokens/vídeo; arredondar como $0.001 no cost log |
| TTS — 60s de narração (~900 chars) | $0.014 | OpenAI TTS $0.015/1k chars |
| Storage — upload R2 (~60MB/vídeo) | $0.001 | $0.015/GB, amortizado |
| YouTube API quota | $0.000 | Gratuita com projeto verificado |
| Compute VPS (amortizado 90 vídeos/mês) | $0.280 | $25/mês ÷ 90 vídeos |
| **TOTAL ESTIMADO** | **~$0.35/vídeo** | ✅ Dentro da meta de $0.40 |

> ⚡ Se o canal validar e o volume subir para 300 vídeos/mês, o custo de compute cai para ~$0.09/vídeo. A meta de $0.20/vídeo é alcançável na fase de escala.

---

## 3. Arquitetura Eficiente

### 3.1 Princípio de Separação de Responsabilidades

A API não processa nada pesado. Cada worker tem uma responsabilidade única. O ContentBrain é o único módulo com permissão de tomar decisões autônomas.

### 3.2 Fluxo de Produção com Pontos de Controle de Custo

| Etapa | Worker | LLM? | Custo | Gate |
|---|---|---|---|---|
| Gerar ideia | idea-worker | ✅ mini | $0.005 | Score mínimo 60 |
| Gerar hook | script-worker | ✅ mini | $0.008 | Hook score > 70 |
| Gerar roteiro | script-worker | ✅ mini | $0.025 | Aprovação humana |
| Otimizar retenção | script-worker | ✅ mini | $0.010 | Auto (regras fixas) |
| Policy Guard | policy-worker | ✅ mini | $0.005 | Bloqueio automático se risk > 60 |
| SimilarityGuard | similarity-worker | ✅ embedding small | ~$0.001 | Bloqueio se similaridade passar dos limites |
| Gerar voz TTS | voice-worker | ❌ | $0.014 | Só após script aprovado |
| Gerar legendas | caption-worker | ❌ Whisper local | $0.000 | Automático |
| Selecionar assets | asset-worker | ❌ pool local | $0.000 | Automático |
| Render preview (720p) | render-worker | ❌ | $0.000 | Aprovação humana |
| Render final (1080p) | render-worker | ❌ | $0.000 | Só após preview ok |
| Gerar metadata | script-worker | ✅ mini | $0.005 | Auto |
| Upload YouTube | upload-worker | ❌ | $0.000 | Status READY_TO_UPLOAD |
| Coletar analytics | analytics-worker | ❌ | $0.000 | Automático por janela |
| ContentBrain update | brain-worker | ❌ regras V1 / ✅ GPT-4o opcional | $0.000–$0.020 | A cada 10 vídeos com analytics 72h |

> ⚡ O ContentBrain V1 decide por regras determinísticas. GPT-4o só é acionado opcionalmente para relatório qualitativo a cada 10 vídeos, mantendo o custo estratégico entre $0.00 e ~$0.002/vídeo.

### 3.3 Render em Dois Estágios — A Decisão Mais Importante

Render em resolução final é caro de compute. A maioria dos sistemas faz um render e descarta se não aprovado. A arquitetura eficiente faz dois estágios:

- **Estágio 1 — Preview 720p:** render rápido (~30s) para aprovação humana. Custo de compute: mínimo.
- **Estágio 2 — Final 1080x1920:** só após aprovação humana do preview. Nunca gera vídeo final de rascunho reprovado.

Isso elimina desperdício de render em conteúdo que seria reprovado de qualquer forma.

---

## 4. Sistema de Cache — Redução de Custo de LLM

Cache bem feito pode reduzir chamadas de LLM em 40–60% conforme o sistema amadurece.

### 4.1 O Que Cachear e Por Quanto Tempo

| Objeto | Cache Key | TTL | Onde |
|---|---|---|---|
| Hook por padrão+nicho | `hook:{niche}:{pattern_hash}` | 7 dias | Redis |
| Roteiro base por template | `script:{template_id}:{topic_hash}` | 3 dias | Redis |
| Policy check de roteiro | `policy:{script_hash}` | 24h | Redis |
| Metadata (título+desc+tags) | `meta:{script_id}` | 30 dias | PostgreSQL |
| Score de ideia por tópico | `idea_score:{topic_hash}:{niche}` | 48h | Redis |
| Assets por tag+mood | `assets:{tag}:{mood}` | 7 dias | PostgreSQL |
| Analytics snapshot por janela | `analytics:{video_id}:{window}` | Permanente | PostgreSQL |

### 4.2 Estratégia de Variação sem Nova Chamada de LLM

Quando um padrão de roteiro performa bem, o sistema não precisa gerar do zero. Usa um roteiro base cacheado e substitui variáveis:

> ⚡ Roteiro base: `"Este {personagem} {verbo} {objeto} há {tempo}."` → reutiliza estrutura, substitui tokens. Custo: $0.00 de LLM.

- O Script Engine mantém um pool de até 50 roteiros base por template
- Variáveis substituíveis: personagem, época, lugar, consequência, twist, CTA
- Toda variação gerada tem um `similarity_score` contra o pool — se > 0.85, descarta e gera outra
- Roteiros base são gerados em batch de 10 por chamada, não um a um

### 4.3 Prompt Engineering para Custo Baixo

- System prompt fixo, nunca dinâmico — não desperdiça tokens
- Pedir JSON estruturado direto — evita parsing e chamadas de correção
- Limitar `max_tokens` por endpoint: roteiro = 600, hook = 80, metadata = 200
- Temperatura 0.7 para roteiros, 0.9 para hooks — mais criativo onde importa
- Usar cache de prefixo da OpenAI para system prompts longos

---

## 5. Asset Engine com Pool Próprio

A estratégia mais eficiente é nunca buscar assets por vídeo. O sistema mantém um pool que cresce autonomamente.

### 5.1 Construção do Pool Inicial

- Download batch de 500 clips do Pexels (licença comercial gratuita) na semana 0
- Tags por: mood (dark, bright, neutral), tema (nature, urban, space, history, abstract), velocidade (slow, medium, fast)
- Cada clip indexado no banco com tags, duração, resolução, source, license_type
- Nenhuma chamada de API de stock durante produção de vídeo — só consulta local

### 5.2 Regras de Reuso com Rotação

| Regra | Parâmetro | Motivo |
|---|---|---|
| Reuso máximo por canal | `max_uses_per_channel = 8` | Evita repetição visível para inscritos |
| Intervalo mínimo entre usos | `min_gap_days = 14` | Inscritos não veem o mesmo clip em 2 semanas |
| Reuso entre canais diferentes | `max_shared_uses_30d = 20` e `min_unique_assets_per_channel = 70%` | Reduz custo sem parecer rede massificada |
| Clips com score visual baixo | `visual_quality_score < 60 → skip` | Não aparecem no pool de produção |
| Expansão automática do pool | `Se pool_available < 50 → batch download` | Nunca fica sem assets |

### 5.3 Geração de Imagem com IA — Apenas como Último Recurso

Geração via DALL-E ou similar só deve acontecer se:

- O pool local não tem nenhum asset adequado para o tópico
- O tema é muito específico (ex: "imperador romano declarando guerra ao mar")
- O custo estimado de geração é aprovado automaticamente por estar abaixo de $0.04

> ⚡ Custo de DALL-E 3 (1024x1792): $0.080/imagem. Só usar se não houver alternativa. Imagens geradas entram no pool e podem ser reusadas.

---

## 6. ContentBrain — Lógica Concreta de Aprendizado

Este é o módulo mais estratégico. A V2.1 define o ContentBrain como um sistema **determinístico na decisão** e **assistido por LLM apenas na interpretação**.

A regra central é:

```txt
Decisão automática = regras + métricas + confiança estatística
LLM opcional = explicação qualitativa + hipóteses + sugestões de pauta
```

Isso reduz custo, aumenta previsibilidade e evita que uma IA tome decisões instáveis sobre escala, pausa ou repetição de padrões.

### 6.1 Quando o ContentBrain Roda

- A cada 10 vídeos publicados com analytics da janela de 72h coletados
- Nunca por vídeo individual — acumula dados para reduzir ruído
- Máximo 1x por dia, mesmo que o volume seja alto
- Só executa ações automáticas se `sample_size >= 5` e `confidence >= 0.60`
- GPT-4o é opcional e só gera relatório qualitativo; não decide `repeat_pattern`, `pause_pattern` ou `scale_channel`

### 6.2 Classificação Híbrida de Performance

A classificação não deve depender apenas de views fixas. Canal novo, canal médio e canal validado têm escalas diferentes.

Por isso, o ContentBrain usa dois sinais:

```txt
fixed_threshold_score = classificação por números absolutos
channel_percentile_score = classificação pela posição do vídeo dentro do próprio canal
final_performance_class = max(fixed_threshold_score, channel_percentile_score)
```

#### 6.2.1 Thresholds Fixos

| Classificação | Views 72h | Retenção Média | Completion Rate | Ação |
|---|---:|---:|---:|---|
| 🔴 Flop | < 200 | < 30% | < 25% | Marcar padrão como fraco |
| ⚠️ Abaixo da média | 200–800 | 30–45% | 25–40% | Monitorar mais 5 vídeos |
| ✅ Ok | 800–3.000 | 45–60% | 40–55% | Manter padrão, sem ação |
| ✅ Bom | 3.000–15.000 | 60–70% | 55–65% | Gerar 5 variações |
| 🟢 Viral Candidate | 15.000–100.000 | > 70% | > 65% | Gerar 10 variações urgente |
| 🟢 Viral | > 100.000 | > 75% | > 70% | Máxima prioridade, replicar padrão |

#### 6.2.2 Percentil Interno do Canal

| Percentil no canal | Classificação relativa | Uso |
|---:|---|---|
| < P40 | Flop relativo | Evitar padrão se repetir |
| P40–P70 | Normal | Manter observação |
| P70–P90 | Winner relativo | Testar variações |
| P90–P95 | Breakout relativo | Priorizar no próximo lote |
| > P95 | Viral relativo | Criar campanha derivada |

Exemplo: se um canal novo ainda tem poucas views, um vídeo com 1.200 views pode ser classificado como `Winner relativo` se estiver acima do P90 do próprio canal. Isso evita que o sistema ignore sinais iniciais só porque ainda não atingiram thresholds absolutos.

### 6.3 Cálculo do Score de Vídeo

Cada vídeo recebe um score de 0 a 100:

```txt
video_score =
  views_percentile_72h * 0.35
+ retention_score * 0.30
+ completion_score * 0.20
+ subs_per_1000_views_score * 0.10
+ comments_per_1000_views_score * 0.05
```

Normalização:

- `views_percentile_72h`: percentil do vídeo dentro do canal na janela de 72h
- `retention_score`: retenção média convertida para escala 0–100
- `completion_score`: completion rate convertido para escala 0–100
- `subs_per_1000_views_score`: normalizado contra média do canal
- `comments_per_1000_views_score`: normalizado contra média do canal

### 6.4 Extração de Padrão — Algoritmo Exato

Todo vídeo publicado gera um registro em `video_patterns`. O ContentBrain nunca analisa apenas vídeos vencedores; ele compara vencedores, medianos e perdedores.

Atributos extraídos por vídeo:

```txt
hook_style
template_id
topic_category
duration_bucket
voice_profile_id
caption_style
cta_type
emotion_type
curiosity_gap_type
visual_density
cut_frequency
posting_hour
language
channel_id
```

Quando 3 ou mais vídeos do mesmo padrão atingem "Bom" ou acima:

- Calcular `pattern_score` com peso: views 35%, retenção 30%, completion 20%, inscritos 10%, comentários 5%
- Calcular `confidence = n_videos_acima_da_media / total_no_padrao`
- Armazenar como `winning_pattern` se `confidence >= 0.60` e `sample_size >= 5`
- Marcar como `weak_pattern` se tiver 3 flops consecutivos ou score abaixo de P40 em 5 execuções

### 6.5 Ações Automáticas por Tipo de Decisão

| Decisão | Trigger | Ação Automática | Aprovação? |
|---|---|---|---|
| `repeat_pattern` | `sample_size >= 5` e `confidence >= 0.60` | Enfileirar 10 variações na próxima campanha | Não |
| `pause_pattern` | 3 flops consecutivos ou 5 vídeos abaixo de P40 | Bloquear `pattern_id` na fila de ideias por 14 dias | Não |
| `test_variation` | Bom absoluto ou P70–P90, mas `confidence < 0.60` | Gerar 3 variações com 1 variável diferente | Não |
| `escalate_channel` | Canal com 5 `winning_patterns` ativos e custo/vídeo < $0.40 | Notificar humano para revisão de escala | Sim |
| `change_niche` | Canal sem `winning_pattern` em 60 dias e média abaixo de P50 global | Gerar relatório + sugerir pivô | Sim |
| `require_human_review` | Similaridade alta, risco de policy ou custo fora da meta | Bloquear avanço até aprovação | Sim |

### 6.6 Feedback Loop Completo

- Analytics 72h coletado → ContentBrain classifica → padrão extraído, pausado ou mantido
- Padrão vencedor → Idea Engine prioriza tópicos compatíveis → Hook Engine usa hooks similares
- Padrão perdedor → Idea Engine reduz prioridade da categoria → Hook Engine evita estilo
- Score de ideia nova leva em conta `winning_patterns` e `weak_patterns` ativos do canal
- SimilarityGuard valida se a variação é realmente nova antes de permitir produção

> ⚡ O Idea Engine consulta `winning_patterns`, `weak_patterns` e `video_patterns` ao gerar ideias. Ideias compatíveis com um padrão vencedor ativo ganham +20 no `idea_score`; ideias parecidas com padrões pausados perdem -25.

### 6.7 Papel do GPT-4o no ContentBrain

O GPT-4o não decide ações automáticas na V2.1.

Uso permitido:

- resumir por que um padrão venceu;
- sugerir hipóteses de variação;
- sugerir ângulos editoriais;
- gerar relatório para revisão humana;
- explicar por que um nicho parece fraco.

Uso proibido:

- decidir sozinho escalar canal;
- liberar upload;
- ignorar Safety Gates;
- substituir thresholds de `confidence`;
- repetir padrão com `similarity_score` alto.

## 7. Modelo de Dados — Adições para Eficiência

As tabelas da V1 são mantidas. Adicionam-se as tabelas críticas que a V1 não tinha.

### 7.1 Tabela: `llm_cache`

Evita chamadas duplicadas de LLM.

```sql
CREATE TABLE llm_cache (
  id UUID PRIMARY KEY,
  cache_key TEXT UNIQUE NOT NULL,
  prompt_hash TEXT NOT NULL,
  model TEXT NOT NULL,
  response_text TEXT NOT NULL,
  tokens_used INT,
  expires_at TIMESTAMP,
  hit_count INT DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### 7.2 Tabela: `video_patterns`

Salva o DNA de todo vídeo publicado ou produzido, inclusive flops. É a base para comparar o que funcionou contra o que falhou. Na V2.2, também armazena referências dos embeddings usados pelo SimilarityGuard.

```sql
CREATE TABLE video_patterns (
  id UUID PRIMARY KEY,
  video_id UUID REFERENCES videos(id),
  channel_id UUID REFERENCES channels(id),
  hook_style TEXT,
  template_id UUID,
  topic_category TEXT,
  duration_bucket TEXT,
  voice_profile_id UUID,
  caption_style TEXT,
  cta_type TEXT,
  emotion_type TEXT,
  curiosity_gap_type TEXT,
  visual_density TEXT,
  cut_frequency NUMERIC,
  posting_hour INT,
  language TEXT,
  script_hash TEXT,
  hook_hash TEXT,
  title_hash TEXT,
  script_embedding_id UUID,
  hook_embedding_id UUID,
  title_embedding_id UUID,
  performance_class TEXT,
  video_score NUMERIC,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### 7.3 Tabela: `winning_patterns`

Base do ContentBrain. Armazena padrões validados por dados.

```sql
CREATE TABLE winning_patterns (
  id UUID PRIMARY KEY,
  channel_id UUID REFERENCES channels(id),
  hook_style TEXT,
  template_id UUID,
  topic_category TEXT,
  duration_bucket TEXT,
  voice_profile_id UUID,
  avg_views NUMERIC,
  avg_retention NUMERIC,
  avg_completion NUMERIC,
  pattern_score NUMERIC,
  confidence NUMERIC,
  sample_size INT,
  status TEXT DEFAULT 'active',
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
```

### 7.4 Tabela: `weak_patterns`

Armazena padrões pausados ou evitados pelo ContentBrain.

```sql
CREATE TABLE weak_patterns (
  id UUID PRIMARY KEY,
  channel_id UUID REFERENCES channels(id),
  hook_style TEXT,
  template_id UUID,
  topic_category TEXT,
  duration_bucket TEXT,
  reason TEXT NOT NULL,
  avg_views NUMERIC,
  avg_retention NUMERIC,
  avg_completion NUMERIC,
  pattern_score NUMERIC,
  sample_size INT,
  blocked_until TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### 7.5 Tabela: `similarity_checks`

Registra checagens de similaridade para evitar conteúdo repetitivo.

```sql
CREATE TABLE similarity_checks (
  id UUID PRIMARY KEY,
  video_id UUID REFERENCES videos(id),
  compared_against_video_id UUID REFERENCES videos(id),
  script_similarity NUMERIC,
  hook_similarity NUMERIC,
  title_similarity NUMERIC,
  embedding_model TEXT DEFAULT 'text-embedding-3-small',
  asset_sequence_similarity NUMERIC,
  overall_similarity NUMERIC,
  action TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### 7.5.1 Tabela: `content_embeddings`

Armazena embeddings uma única vez por hash de conteúdo. O SimilarityGuard nunca deve gerar embedding duplicado para o mesmo texto.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE content_embeddings (
  id UUID PRIMARY KEY,
  content_hash TEXT UNIQUE NOT NULL,
  content_type TEXT NOT NULL CHECK (content_type IN ('script', 'hook', 'title')),
  model TEXT NOT NULL DEFAULT 'text-embedding-3-small',
  dimensions INT NOT NULL DEFAULT 1536,
  embedding VECTOR(1536) NOT NULL,
  tokens_used INT,
  cost_usd NUMERIC DEFAULT 0.00002,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### 7.6 Tabela: `asset_pool`

```sql
CREATE TABLE asset_pool (
  id UUID PRIMARY KEY,
  storage_path TEXT NOT NULL,
  source TEXT NOT NULL,
  license_type TEXT NOT NULL,
  tags TEXT[],
  mood TEXT,
  theme TEXT,
  duration_seconds NUMERIC,
  visual_quality_score INT DEFAULT 80,
  uses_total INT DEFAULT 0,
  last_used_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### 7.7 Tabela: `cost_budget`

Controle de orçamento diário por canal. Bloqueia produção se limite atingido.

```sql
CREATE TABLE cost_budget (
  id UUID PRIMARY KEY,
  channel_id UUID REFERENCES channels(id),
  date DATE NOT NULL,
  budget_usd NUMERIC NOT NULL DEFAULT 5.00,
  spent_usd NUMERIC NOT NULL DEFAULT 0.00,
  videos_produced INT DEFAULT 0,
  status TEXT DEFAULT 'active',
  UNIQUE(channel_id, date)
);
```

---


### 7.8 Índices Recomendados

```sql
CREATE INDEX idx_video_patterns_channel_score
  ON video_patterns(channel_id, video_score DESC);

CREATE INDEX idx_winning_patterns_channel_status
  ON winning_patterns(channel_id, status);

CREATE INDEX idx_weak_patterns_channel_blocked
  ON weak_patterns(channel_id, blocked_until);

CREATE INDEX idx_similarity_checks_video
  ON similarity_checks(video_id);

CREATE INDEX idx_content_embeddings_hash
  ON content_embeddings(content_hash);

CREATE INDEX idx_content_embeddings_vector
  ON content_embeddings USING ivfflat (embedding vector_cosine_ops);

CREATE INDEX idx_asset_pool_theme_mood_quality
  ON asset_pool(theme, mood, visual_quality_score DESC);
```

## 8. Providers — Decisões Fechadas

Nenhuma decisão de provider em aberto. Tudo definido com custo documentado.

### 8.1 LLM

| Módulo | Model | Max Tokens | Temp | Custo Est. |
|---|---|---|---|---|
| Idea Engine | gpt-4o-mini | 300 | 0.8 | $0.005/batch |
| Hook Engine | gpt-4o-mini | 100 | 0.9 | $0.002/hook |
| Script Engine | gpt-4o-mini | 600 | 0.7 | $0.025/roteiro |
| Retention Optimizer | gpt-4o-mini | 400 | 0.5 | $0.010/opt |
| Policy Guard | gpt-4o-mini | 200 | 0.3 | $0.005/check |
| Metadata Generator | gpt-4o-mini | 250 | 0.6 | $0.005/vídeo |
| ContentBrain (decisão V1) | regras determinísticas | N/A | N/A | $0.000/10 vídeos |
| ContentBrain Report (opcional) | gpt-4o | 800 | 0.4 | $0.020/10 vídeos |

### 8.2 Embeddings

O SimilarityGuard V1 usa embeddings via API da OpenAI, não modelo local. A decisão é fechada para reduzir setup, evitar dependência pesada no VPS e manter custo praticamente irrelevante.

| Uso | Provider | Modelo | Dimensões | Custo | Decisão |
|---|---|---|---|---|---|
| Roteiro, hook e título | OpenAI | `text-embedding-3-small` | 1536 | ~$0.02/1M tokens | ✅ Provider principal do MVP |
| Comparação vetorial | PostgreSQL + pgvector | Cosine distance | 1536 | $0.00 local | ✅ Similaridade roda no banco |
| Cache | `content_embeddings` por `content_hash` | N/A | N/A | Evita duplicação | ✅ Obrigatório |
| Fallback futuro | `sentence-transformers/all-MiniLM-L6-v2` local | 384 | $0.00 | Só fase 4+, se custo/API virar problema |

#### Regra operacional

```txt
1. Gerar SHA256 do script, hook e título.
2. Consultar content_embeddings por content_hash.
3. Se já existe, reutilizar embedding. Custo: $0.00.
4. Se não existe, chamar text-embedding-3-small uma vez.
5. Salvar embedding em pgvector.
6. Comparar contra vídeos recentes do mesmo canal e contra vídeos com pattern similar.
```

#### Custo estimado

Um vídeo curto usa aproximadamente 800–1.000 tokens somando roteiro, hook e título. Com `text-embedding-3-small` a ~$0.02 por 1M tokens, o custo real fica perto de **$0.00002 por vídeo**. Para simplificar logs e margem de erro, o sistema registra **$0.001/vídeo** como teto contábil do SimilarityGuard.

#### Escopo de comparação no MVP

Para evitar custo computacional desnecessário, o MVP não compara contra todo o histórico. A busca vetorial compara apenas contra:

- últimos 200 vídeos do mesmo canal;
- vídeos dos últimos 90 dias com mesmo `topic_category`;
- vídeos com mesmo `hook_style`;
- vídeos com o mesmo `template_id`;
- qualquer vídeo marcado como `winning_pattern` ou `weak_pattern`.

### 8.3 TTS

| Provider | Model | Custo | Qualidade | Decisão |
|---|---|---|---|---|
| OpenAI TTS | tts-1 | $0.015/1k chars | Boa | ✅ Provider principal |
| OpenAI TTS HD | tts-1-hd | $0.030/1k chars | Excelente | Reservado para canais validados |
| ElevenLabs | Starter | $0.30/1k chars | Excelente | ❌ Caro demais para MVP |
| Google TTS | Neural2 | $0.016/1k chars | Boa | Fallback se OpenAI cair |

Voz padrão MVP: OpenAI tts-1, voz `onyx` (narrativa masculina) ou `nova` (feminina). Uma voz por canal. Não trocar sem validar impacto.

### 8.4 Storage e Infraestrutura

| Serviço | Provider | Custo | Motivo |
|---|---|---|---|
| Object Storage | Cloudflare R2 | $0.015/GB + free egress | Zero custo de saída vs S3 |
| VPS (MVP) | Hetzner CPX41 | ~$25/mês (8vCPU/16GB) | Melhor custo/performance |
| Banco (MVP) | Local no VPS | $0.00 | Migra para gerenciado só na fase 4 |
| Redis (MVP) | Local no VPS | $0.00 | Upstash só se VPS ficar apertado |
| CDN | Cloudflare Free | $0.00 | Suficiente para dashboard |
| SSL | Let's Encrypt | $0.00 | Automático via Certbot |

---

## 9. Geração de Legendas com Whisper Local

### 9.1 Por Que Whisper Local

| Alternativa | Custo | Qualidade | Decisão |
|---|---|---|---|
| OpenAI Whisper API | $0.006/min de áudio | Excelente | ⚠️ Aceitável, mas tem custo |
| Whisper local (tiny) | $0.00 | Boa | ✅ Para MVP e canais em inglês |
| Whisper local (base) | $0.00 | Muito boa | ✅ Recomendado |
| AssemblyAI | $0.0115/min | Excelente + alinhamento | Reservado para escala |

### 9.2 Pipeline de Legenda

- Áudio TTS gerado → Whisper base roda localmente → JSON com timestamps por palavra
- Highlights gerados por regra: palavras > 5 letras em posição de ênfase do roteiro
- Quebras de linha automáticas: máximo 3 palavras por linha para Shorts
- Tempo total de processing: ~15–30s para 60s de áudio com Whisper base no VPS

---

## 10. Render Engine — FFmpeg First

Remotion é poderoso mas tem overhead. Para templates definidos, FFmpeg puro é mais rápido e mais barato de compute.

### 10.1 Quando Usar o Quê

| Template | Tecnologia | Tempo Render | Motivo |
|---|---|---|---|
| dark_documentary_v1 | FFmpeg puro | ~45s para 45s de vídeo | Transições simples, clips sequenciais |
| finance_fast_v1 | FFmpeg puro | ~30s | Texto sobre background, sem animação complexa |
| science_visual_v1 | Remotion | ~90s | Animações e gráficos interativos |
| Templates customizados futuros | Remotion | Variável | Quando precisar de lógica React |

### 10.2 Pipeline FFmpeg para `dark_documentary_v1`

- Montar lista de clips do pool (`asset_pool`) compatíveis com duração e tema
- Concatenar clips com filtro de crossfade suave (0.3s)
- Overlay do áudio TTS normalizado (-16 LUFS)
- Overlay das legendas via subtítulos ASS com estilo do template
- Output preview: 1280x720, CRF 28, preset fast — ~20MB
- Output final: 1080x1920, CRF 22, preset medium — ~60MB

> ⚡ Tempo estimado de render no Hetzner CPX41: preview em ~20s, final em ~50s. Sem GPU, sem custo adicional.

---

## 11. Idempotência e Safety Gates

### 11.1 Gates por Etapa — Nunca Avança sem Critério

| Etapa | Gate de Entrada | Falha → Ação |
|---|---|---|
| Gerar roteiro | `idea_score ≥ 60` | Descartar ideia, gerar próxima |
| Gerar TTS | `script status = SCRIPT_APPROVED` | Bloquear, aguardar humano |
| Render final | `preview status = RENDER_PREVIEW_APPROVED` | Bloquear, aguardar humano |
| Upload | `status = READY_TO_UPLOAD AND policy_approved = true` | Hard block, log crítico |
| ContentBrain action | `sample_size ≥ 5 E confidence ≥ 0.60` | Aguardar mais dados |
| Budget check | `spent_usd < budget_usd do dia` | Pausar fila do canal |

### 11.2 Proteções de Upload — Crítico

- Cada upload tem um `idempotency_key = SHA256(video_id + channel_id + scheduled_date)`
- Antes de qualquer chamada à YouTube API, checar se `idempotency_key` já existe na tabela `uploads`
- Se existe com `status = SUCCESS` → retornar `youtube_video_id` existente, não fazer nova chamada
- Retry de upload: máximo 3 tentativas com backoff exponencial de 5min, 15min, 60min
- Após 3 falhas: `status = UPLOAD_FAILED`, alerta humano obrigatório

---

## 12. SimilarityGuard — Controle de Conteúdo Repetitivo

O SimilarityGuard evita que o sistema produza vídeos muito parecidos entre si. Ele é obrigatório porque eficiência não pode virar aparência de conteúdo massificado.

### 12.1 O Que Comparar

| Item | Técnica V1 | Bloqueio |
|---|---|---|
| Roteiro | `text-embedding-3-small` + cosseno no pgvector | `script_similarity > 0.85` |
| Hook | `text-embedding-3-small` + comparação lexical | `hook_similarity > 0.90` |
| Título | `text-embedding-3-small` + similaridade textual | `title_similarity > 0.88` |
| Sequência de assets | Jaccard dos `asset_id` usados | `asset_sequence_similarity > 0.70` |
| Pattern geral | Comparação de atributos do `video_patterns` | `overall_similarity > 0.85` |

### 12.2 Implementação de Embedding no MVP

Decisão fechada:

```txt
provider = OpenAI
model = text-embedding-3-small
dimensions = 1536
storage = PostgreSQL + pgvector
comparison = cosine similarity
fallback_local = não usar no MVP
```

Justificativa: o custo por vídeo é quase zero, o setup é simples e o resultado é melhor que heurística lexical pura. Modelo local só entra depois se a operação estiver em escala alta ou se houver necessidade de reduzir dependência de API externa.

O SimilarityGuard deve rodar antes de TTS e render. Se o roteiro for bloqueado por similaridade, nada caro é produzido.

### 12.3 Ações

| Resultado | Ação |
|---|---|
| `overall_similarity <= 0.70` | Liberar produção |
| `0.70 < overall_similarity <= 0.85` | Gerar nova variação alterando 1 variável |
| `overall_similarity > 0.85` | Bloquear e exigir nova ideia |
| `script_similarity > 0.90` | Bloqueio imediato |
| `asset_sequence_similarity > 0.70` | Trocar assets antes do preview |

### 12.4 Variáveis Que Devem Mudar em Variações

Ao repetir um padrão vencedor, o sistema deve manter a estrutura vencedora, mas alterar pelo menos 3 variáveis:

```txt
topic_entity
story_angle
hook_wording
asset_sequence
cta
posting_hour
caption_emphasis
```

Regra:

```txt
repetir padrão ≠ copiar vídeo
```

O objetivo é preservar o que performou sem criar conteúdo repetitivo.

---

## 13. Observabilidade de Custo em Tempo Real

### 13.1 Dashboard de Custo (Prioridade Alta no MVP)

O dashboard deve mostrar sempre visível:

- Custo total do dia por canal
- Custo médio por vídeo (rolling 30 dias)
- Breakdown: LLM / TTS / Storage / Compute
- Alerta visual se custo/vídeo > $0.50
- Projeção de custo mensal baseado no ritmo atual

### 13.2 Alertas Automáticos

| Condição | Ação | Urgência |
|---|---|---|
| Custo diário > 120% do orçamento | Pausar fila + notificar | Alta |
| Custo/vídeo > $0.60 (3 vídeos consecutivos) | Alerta + revisão do pipeline | Média |
| Cache hit rate < 20% | Revisar estratégia de cache | Baixa |
| Pool de assets < 50 clips disponíveis | Trigger batch download automático | Média |
| LLM latency > 8s por chamada | Log + investigar | Baixa |
| Upload quota > 80% usada | Alertar + planejar próximo dia | Alta |

---

## 14. Roadmap com Foco em Eficiência

### Fase 0 — Setup (Semana 0)

- [ ] Repositório + Docker Compose + PostgreSQL + Redis
- [ ] Download batch de 500 clips Pexels licenciados + indexação no `asset_pool`
- [ ] Configurar OpenAI API + Whisper local
- [ ] Definir canal, nicho, voz TTS, template inicial
- [ ] Criar `.env` com todos os providers e limites de custo

### Fase 1 — MVP de Produção (Semanas 1–3)

- [ ] FastAPI com endpoints de campanha, roteiro, status
- [ ] Script Engine com GPT-4o-mini + cache Redis
- [ ] TTS Worker com OpenAI tts-1
- [ ] Caption Worker com Whisper local
- [ ] Render Worker FFmpeg (`dark_documentary_v1`)
- [ ] Dashboard básico com status e aprovação
- [ ] `cost_logs` funcionando desde o primeiro vídeo
- [ ] Tabela `video_patterns` preenchida para todo vídeo produzido
- [ ] SimilarityGuard V1 com `text-embedding-3-small`, pgvector e bloqueio de roteiros com similaridade > 0.85
- **Meta:** 10 vídeos produzidos na fase 1

### Fase 2 — Fila e Automação (Semanas 4–5)

- [ ] Celery + filas separadas por tipo de worker
- [ ] Retry com backoff por tipo de job
- [ ] Budget check automático por canal/dia
- [ ] Asset pool com rotação automática
- [ ] Preview render separado do final

### Fase 3 — Upload e Analytics (Semanas 6–8)

- [ ] OAuth YouTube + upload via API com idempotência
- [ ] Analytics Worker com janelas 1h/6h/24h/72h/7d/30d
- [ ] Dashboard de performance por vídeo
- **Meta:** 90 vídeos publicados, custo/vídeo documentado

### Fase 4 — ContentBrain (Semanas 9–10)

- [ ] Tabela `winning_patterns` preenchida com primeiros dados reais
- [ ] Lógica de classificação e extração de padrão
- [ ] Feedback loop Idea Engine ← ContentBrain ativado
- [ ] Primeiro relatório automático de padrões

### Fase 5 — Escala Consciente (Após validação)

- [ ] Escala apenas com: custo/vídeo < $0.40, `winning_pattern` identificado, canal saudável
- [ ] Segundo canal só após 90 dias do primeiro
- [ ] Multicanal com isolamento total de orçamento

---

## 15. Definição de Pronto — Versão Eficiente

### Um vídeo está pronto para upload quando:

| Critério | Verificação | Automático? |
|---|---|---|
| Script aprovado por humano | `status = SCRIPT_APPROVED` | ❌ Humano |
| Policy Guard aprovado | `policy_approved = true AND risk_score < 60` | ✅ |
| TTS gerado e normalizado | `audio_path != null AND audio_lufs BETWEEN -18 AND -14` | ✅ |
| Legendas alinhadas | `captions_path != null AND word_count_match = true` | ✅ |
| Assets com licença registrada | Todos assets com `license_type != null` | ✅ |
| Preview aprovado por humano | `preview_approved = true` | ❌ Humano |
| Render final concluído | `render_status = READY AND size_mb > 5` | ✅ |
| Metadata gerada | `title != null AND description != null AND tags != null` | ✅ |
| Idempotency key criada | `idempotency_key != null` | ✅ |
| Budget do dia não estourado | `spent_usd < budget_usd` | ✅ |
| **Status final** | **`status = READY_TO_UPLOAD`** | ✅ (todos acima ok) |

### O sistema é eficiente quando:

- Custo médio por vídeo < $0.40 por 30 dias consecutivos
- Cache hit rate de LLM > 30%
- Tempo médio de produção (ideia → render) < 12 minutos
- Taxa de reprovação de policy < 15%
- Pool de assets sempre acima de 100 clips disponíveis
- Nenhum upload duplicado em 90 dias de operação
- Nenhum vídeo publicado com `overall_similarity > 0.85` em 90 dias

---

## 16. Riscos de Eficiência e Mitigações

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| LLM caro por prompts longos | Alta | Alto | max_tokens fixo, prompt compacto, cache |
| TTS regerado por bug | Média | Médio | Verificar hash antes de gerar, nunca sobrescrever |
| Render final de vídeo reprovado | Média | Alto | Preview 720p obrigatório antes do final |
| Pool de assets esgotado | Baixa | Alto | Alert em < 50 clips + batch automático |
| Custo diário explodindo | Média | Alto | Budget lock por canal/dia, hard stop |
| ContentBrain decidindo com dados insuficientes | Baixa | Médio | Mínimo de 5 vídeos + confidence ≥ 0.60 |
| Upload duplicado no YouTube | Baixa | Alto | Idempotency key + check antes da chamada API |
| VPS sem memória durante render | Média | Médio | Max 2 renders simultâneos, fila controlada |
| Conteúdo repetitivo por excesso de variação automática | Média | Alto | SimilarityGuard com `text-embedding-3-small`, video_patterns, limite de reuso de assets |

---

*ShortsFactory — Efficiency Edition v2.2 · Otávio Juliano · 2026*
