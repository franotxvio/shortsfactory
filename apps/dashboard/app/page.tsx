"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type VideoItem = {
  video_id: number;
  video_slug?: string | null;
  channel_slug?: string | null;
  status: string;
  stage_status: string;
  is_demo?: boolean;
  script_id?: number | null;
  script_status?: string | null;
  asset_id?: number | null;
  audio_path?: string | null;
  caption_path?: string | null;
  preview_path?: string | null;
  final_path?: string | null;
  asset_path?: string | null;
  asset_name?: string | null;
  asset_slug?: string | null;
  asset_type?: string | null;
  asset_channel_slug?: string | null;
  asset_topic?: string | null;
  asset_tags?: string[] | null;
  preview_approved_at?: string | null;
  script_text?: string | null;
  hook?: string | null;
  body_blocks?: string[] | null;
  call_to_action?: string | null;
  estimated_duration_seconds?: number | null;
  style_tone?: string | null;
};

type AssetItem = {
  asset_id: number;
  asset_type: string;
  name: string;
  slug: string;
  source_path?: string | null;
  license_name: string;
  license_url?: string | null;
  status: string;
  channel_slug?: string | null;
  topic?: string | null;
  tags?: string[] | null;
  is_default?: boolean;
};

type VideoListResponse = {
  items: VideoItem[];
};

type AssetListResponse = {
  items: AssetItem[];
};

type MessageState = {
  kind: "idle" | "success" | "error";
  text: string;
};

const DEFAULT_API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

const DEFAULT_FORM = {
  topic: "Como aprender Python",
  channelSlug: "manual-test",
  channelName: "Manual Test",
  videoTitle: "Teste manual",
};

function normalizeBaseUrl(value: string) {
  return value.trim().replace(/\/+$/, "");
}

async function requestJson<T>(baseUrl: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${normalizeBaseUrl(baseUrl)}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed with status ${response.status}`);
  }

  return (await response.json()) as T;
}

function PathLine({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="path-row">
      <span className="path-label">{label}</span>
      <code className={`path-value${value ? "" : " is-empty"}`}>{value ?? "pending"}</code>
    </div>
  );
}

function AssetTags({ tags }: { tags?: string[] | null }) {
  if (!tags?.length) {
    return null;
  }

  return (
    <div className="badge-row">
      {tags.map((tag) => (
        <span key={tag} className="badge subtle">
          {tag}
        </span>
      ))}
    </div>
  );
}

function FileLinks({
  apiBaseUrl,
  video,
}: {
  apiBaseUrl: string;
  video: VideoItem;
}) {
  const links = [
    { label: "Abrir preview", path: video.preview_path },
    { label: "Abrir final", path: video.final_path },
    { label: "Abrir captions", path: video.caption_path },
    { label: "Abrir asset", path: video.asset_path },
  ].filter((item) => Boolean(item.path));

  if (links.length === 0) {
    return null;
  }

  return (
    <div className="file-links">
      {links.map((item) => (
        <a
          key={item.label}
          className="file-link"
          href={`${normalizeBaseUrl(apiBaseUrl)}/internal/videos/files?path=${encodeURIComponent(item.path ?? "")}`}
          target="_blank"
          rel="noreferrer"
        >
          {item.label}
        </a>
      ))}
    </div>
  );
}

export default function DashboardPage() {
  const [apiBaseUrl, setApiBaseUrl] = useState(DEFAULT_API_BASE_URL);
  const apiBaseUrlRef = useRef(DEFAULT_API_BASE_URL);
  const [topic, setTopic] = useState(DEFAULT_FORM.topic);
  const [channelSlug, setChannelSlug] = useState(DEFAULT_FORM.channelSlug);
  const [channelName, setChannelName] = useState(DEFAULT_FORM.channelName);
  const [videoTitle, setVideoTitle] = useState(DEFAULT_FORM.videoTitle);
  const [videos, setVideos] = useState<VideoItem[]>([]);
  const [assets, setAssets] = useState<AssetItem[]>([]);
  const [selectedVideoId, setSelectedVideoId] = useState<number | null>(null);
  const selectedVideoIdRef = useRef<number | null>(null);
  const [scriptDraft, setScriptDraft] = useState("");
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<MessageState>({ kind: "idle", text: "" });

  const selectedVideo = useMemo(
    () => videos.find((video) => video.video_id === selectedVideoId) ?? null,
    [selectedVideoId, videos],
  );
  const scriptEditable = selectedVideo?.stage_status === "script_approved";
  const pipelineCompleted =
    selectedVideo?.stage_status === "final_rendered" || selectedVideo?.status === "completed";

  function buildScriptDraft(video: VideoItem | null) {
    if (!video) {
      return "";
    }
    if (video.script_text) {
      return video.script_text;
    }
    const sections = [video.hook, ...(video.body_blocks ?? []), video.call_to_action].filter(Boolean);
    return sections.join("\n\n");
  }

  function canRunStep(video: VideoItem | null, stage: string) {
    if (!video) {
      return false;
    }
    const order = [
      "script_approved",
      "tts_done",
      "caption_done",
      "asset_ready",
      "preview_ready",
      "preview_approved",
      "final_rendered",
    ];
    const currentIndex = order.indexOf(video.stage_status);
    const targetIndex = order.indexOf(stage);
    return currentIndex === targetIndex - 1;
  }

  function canSelectAsset(video: VideoItem | null) {
    return video?.stage_status === "caption_done" || video?.stage_status === "asset_ready";
  }

  useEffect(() => {
    apiBaseUrlRef.current = apiBaseUrl;
  }, [apiBaseUrl]);

  useEffect(() => {
    selectedVideoIdRef.current = selectedVideoId;
  }, [selectedVideoId]);

  const loadVideos = useCallback(async (options?: { baseUrl?: string; quiet?: boolean }) => {
    const baseUrl = options?.baseUrl ?? apiBaseUrlRef.current;
    const quiet = options?.quiet ?? false;
    setLoading(true);
    try {
      const payload = await requestJson<VideoListResponse>(baseUrl, "/internal/videos");
      const items = payload.items ?? [];
      setVideos(items);
      const nextSelectedId =
        selectedVideoIdRef.current !== null && items.some((item) => item.video_id === selectedVideoIdRef.current)
          ? selectedVideoIdRef.current
          : items[0]?.video_id ?? null;
      setSelectedVideoId(nextSelectedId);
      setScriptDraft(buildScriptDraft(items.find((item) => item.video_id === nextSelectedId) ?? null));
      if (!quiet) {
        setMessage({ kind: "success", text: `Foram carregados ${items.length} videos.` });
      }
    } catch (error) {
      if (!quiet) {
        setMessage({ kind: "error", text: error instanceof Error ? error.message : "Falha ao carregar videos." });
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const loadAssets = useCallback(async (options?: { baseUrl?: string; quiet?: boolean }) => {
    const baseUrl = options?.baseUrl ?? apiBaseUrlRef.current;
    const quiet = options?.quiet ?? false;
    try {
      const payload = await requestJson<AssetListResponse>(baseUrl, "/internal/videos/assets");
      const items = payload.items ?? [];
      setAssets(items);
      if (!quiet) {
        setMessage({ kind: "success", text: `Foram carregados ${items.length} assets locais.` });
      }
    } catch (error) {
      if (!quiet) {
        setMessage({ kind: "error", text: error instanceof Error ? error.message : "Falha ao carregar assets." });
      }
    }
  }, []);

  function mergeVideo(nextVideo: VideoItem) {
    setVideos((current) => {
      const index = current.findIndex((item) => item.video_id === nextVideo.video_id);
      if (index === -1) {
        return [nextVideo, ...current];
      }
      const updated = current.slice();
      updated[index] = nextVideo;
      return updated;
    });
    setSelectedVideoId(nextVideo.video_id);
    selectedVideoIdRef.current = nextVideo.video_id;
    setScriptDraft(buildScriptDraft(nextVideo));
  }

  function selectVideo(video: VideoItem) {
    setSelectedVideoId(video.video_id);
    selectedVideoIdRef.current = video.video_id;
    setScriptDraft(buildScriptDraft(video));
  }

  async function createFakeVideo() {
    setBusyAction("create");
    try {
      const created = await requestJson<VideoItem>(apiBaseUrl, "/internal/videos/test", {
        method: "POST",
        body: JSON.stringify({
          topic,
          channel_slug: channelSlug,
          channel_name: channelName,
          video_title: videoTitle,
          execution_mode: "fake",
        }),
      });
      mergeVideo(created);
      setMessage({ kind: "success", text: `Video ${created.video_id} criado em modo fake.` });
      void loadVideos({ quiet: true });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "Falha ao criar video fake." });
    } finally {
      setBusyAction(null);
    }
  }

  async function produceFakePipeline() {
    if (selectedVideoId === null) {
      setMessage({ kind: "error", text: "Selecione um video antes de produzir o pipeline." });
      return;
    }

    setBusyAction("produce");
    try {
      if (pipelineCompleted) {
        setMessage({
          kind: "success",
          text: `Video ${selectedVideoId} ja esta concluido. Mostrando o estado atual.`,
        });
        return;
      }
      const produced = await requestJson<VideoItem>(apiBaseUrl, `/internal/videos/${selectedVideoId}/produce`, {
        method: "POST",
        body: JSON.stringify({
          auto_approve_preview: true,
          execution_mode: "fake",
        }),
      });
      mergeVideo(produced);
      setMessage({ kind: "success", text: `Pipeline concluido para o video ${selectedVideoId}.` });
      void loadVideos({ quiet: true });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "Falha ao rodar o pipeline fake." });
    } finally {
      setBusyAction(null);
    }
  }

  async function refreshSelectedStatus() {
    if (selectedVideoId === null) {
      setMessage({ kind: "error", text: "Selecione um video para consultar o status." });
      return;
    }

    setBusyAction("status");
    try {
      const updated = await requestJson<VideoItem>(apiBaseUrl, `/internal/videos/${selectedVideoId}/status`);
      mergeVideo(updated);
      setMessage({ kind: "success", text: `Status atualizado para o video ${selectedVideoId}.` });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "Falha ao consultar status." });
    } finally {
      setBusyAction(null);
    }
  }

  async function saveScriptDraft() {
    if (selectedVideoId === null) {
      setMessage({ kind: "error", text: "Selecione um video antes de salvar o roteiro." });
      return;
    }
    if (!scriptEditable) {
      setMessage({ kind: "error", text: "O roteiro só pode ser editado antes do TTS começar." });
      return;
    }

    setBusyAction("save-script");
    try {
      const updated = await requestJson<VideoItem>(apiBaseUrl, `/internal/videos/${selectedVideoId}/script`, {
        method: "PATCH",
        body: JSON.stringify({
          script_text: scriptDraft,
        }),
      });
      mergeVideo(updated);
      setScriptDraft(buildScriptDraft(updated));
      setMessage({ kind: "success", text: `Roteiro do video ${selectedVideoId} salvo com sucesso.` });
      void loadVideos({ quiet: true });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "Falha ao salvar roteiro." });
    } finally {
      setBusyAction(null);
    }
  }

  async function applyAsset(asset: AssetItem) {
    if (selectedVideoId === null) {
      setMessage({ kind: "error", text: "Selecione um video antes de escolher um asset." });
      return;
    }
    if (!canSelectAsset(selectedVideo)) {
      setMessage({ kind: "error", text: "Asset so pode ser trocado antes do preview, depois das captions." });
      return;
    }

    setBusyAction(`asset-${asset.asset_id}`);
    try {
      const updated = await requestJson<VideoItem>(apiBaseUrl, `/internal/videos/${selectedVideoId}/asset`, {
        method: "POST",
        body: JSON.stringify({
          asset_id: asset.asset_id,
        }),
      });
      mergeVideo(updated);
      setMessage({ kind: "success", text: `Asset ${asset.name} aplicado ao video ${selectedVideoId}.` });
      void loadVideos({ quiet: true });
      void loadAssets({ quiet: true });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "Falha ao aplicar asset." });
    } finally {
      setBusyAction(null);
    }
  }

  async function runPipelineStep(step: "tts" | "captions" | "asset" | "preview" | "approve-preview" | "final") {
    if (selectedVideoId === null) {
      setMessage({ kind: "error", text: "Selecione um video antes de executar uma etapa." });
      return;
    }

    const stepLabels: Record<typeof step, string> = {
      tts: "Gerar TTS",
      captions: "Gerar captions",
      asset: "Selecionar asset",
      preview: "Gerar preview",
      "approve-preview": "Aprovar preview",
      final: "Render final",
    };
    const stepPaths: Record<typeof step, string> = {
      tts: `/internal/videos/${selectedVideoId}/tts`,
      captions: `/internal/videos/${selectedVideoId}/captions`,
      asset: `/internal/videos/${selectedVideoId}/asset`,
      preview: `/internal/videos/${selectedVideoId}/preview`,
      "approve-preview": `/internal/videos/${selectedVideoId}/approve-preview`,
      final: `/internal/videos/${selectedVideoId}/final`,
    };
    const stepModes: Record<typeof step, boolean> = {
      tts: true,
      captions: true,
      asset: false,
      preview: false,
      "approve-preview": false,
      final: false,
    };
    const stageRequirements: Record<typeof step, string> = {
      tts: "script_approved",
      captions: "tts_done",
      asset: "caption_done",
      preview: "asset_ready",
      "approve-preview": "preview_ready",
      final: "preview_approved",
    };

    const canRun = step === "asset" ? canSelectAsset(selectedVideo) : canRunStep(selectedVideo, stageRequirements[step]);
    if (!canRun) {
      setMessage({
        kind: "error",
        text: `Nao foi possivel executar ${stepLabels[step]}. Verifique a ordem do pipeline e o stage_status atual.`,
      });
      return;
    }

    setBusyAction(step);
    try {
      const payload = stepModes[step]
        ? { execution_mode: "fake" }
        : undefined;
      const updated = await requestJson<VideoItem>(apiBaseUrl, stepPaths[step], {
        method: "POST",
        body: payload ? JSON.stringify(payload) : undefined,
      });
      mergeVideo(updated);
      setScriptDraft(buildScriptDraft(updated));
      setMessage({ kind: "success", text: `${stepLabels[step]} executado com sucesso.` });
      void loadVideos({ quiet: true });
      void loadAssets({ quiet: true });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : `Falha ao executar ${stepLabels[step]}.` });
    } finally {
      setBusyAction(null);
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadVideos();
      void loadAssets({ quiet: true });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadVideos, loadAssets]);

  return (
    <main className="shell">
      <section className="hero">
        <div>
          <p className="eyebrow">ShortsFactory</p>
          <h1>Dashboard minimo para operar o pipeline local</h1>
          <p className="intro">
            Crie um video fake, rode o pipeline completo, acompanhe o status e confira os paths gerados sem chamar
            OpenAI por padrao.
          </p>
        </div>

        <div className="connection-card">
          <label className="field">
            <span>API base URL</span>
            <input value={apiBaseUrl} onChange={(event) => setApiBaseUrl(event.target.value)} />
          </label>
          <div className="connection-actions">
            <button
              type="button"
              onClick={() => {
                void loadVideos();
                void loadAssets({ quiet: true });
              }}
              disabled={loading}
            >
              {loading ? "Atualizando..." : "Atualizar lista"}
            </button>
            <button type="button" onClick={refreshSelectedStatus} disabled={busyAction !== null}>
              Atualizar status
            </button>
          </div>
        </div>
      </section>

      <section className="grid">
        <aside className="panel">
          <div className="panel-header">
            <h2>Criar video fake</h2>
            <span className="panel-hint">execution_mode = fake</span>
          </div>

          <div className="form-grid">
            <label className="field">
              <span>Tema</span>
              <input value={topic} onChange={(event) => setTopic(event.target.value)} />
            </label>
            <label className="field">
              <span>Slug do canal</span>
              <input value={channelSlug} onChange={(event) => setChannelSlug(event.target.value)} />
            </label>
            <label className="field">
              <span>Nome do canal</span>
              <input value={channelName} onChange={(event) => setChannelName(event.target.value)} />
            </label>
            <label className="field">
              <span>Titulo do video</span>
              <input value={videoTitle} onChange={(event) => setVideoTitle(event.target.value)} />
            </label>
          </div>

          <button type="button" className="primary" onClick={createFakeVideo} disabled={busyAction !== null}>
            {busyAction === "create" ? "Criando..." : "Criar video fake"}
          </button>

          <div className="panel-header spaced">
            <h2>Pipeline fake</h2>
            <span className="panel-hint">video selecionado</span>
          </div>
          <button
            type="button"
            className="primary secondary"
            onClick={produceFakePipeline}
            disabled={busyAction !== null || pipelineCompleted}
          >
            {pipelineCompleted ? "Pipeline concluido" : busyAction === "produce" ? "Processando..." : "Produzir pipeline fake"}
          </button>
          {pipelineCompleted ? <p className="helper">Este video ja esta finalizado. Atualize ou escolha outro item para rodar novamente.</p> : null}

          <div className={`message ${message.kind}`}>
            {message.text || "Pronto para operar o pipeline local."}
          </div>
        </aside>

        <section className="panel">
          <div className="panel-header">
            <h2>Videos recentes</h2>
            <span className="panel-hint">{videos.length} itens</span>
          </div>

          <div className="video-list">
            {videos.length === 0 ? (
              <div className="empty-state">
                Nenhum video encontrado. Crie um video fake para comecar.
              </div>
            ) : (
              videos.map((video) => {
                const isSelected = video.video_id === selectedVideoId;
                return (
                  <button
                    key={video.video_id}
                    type="button"
                    className={`video-card${isSelected ? " selected" : ""}`}
                    onClick={() => selectVideo(video)}
                  >
                    <div className="video-card-top">
                      <div>
                        <p className="video-id">Video #{video.video_id}</p>
                        <h3>{video.video_slug ?? `video-${video.video_id}`}</h3>
                      </div>
                      <div className="badges">
                        <span className="badge">{video.status}</span>
                        <span className="badge accent">{video.stage_status}</span>
                        {video.is_demo ? <span className="badge demo">DEMO / LOCAL</span> : null}
                      </div>
                    </div>
                    <div className="meta-row">
                      <span>script_id: {video.script_id ?? "pending"}</span>
                      <span>script_status: {video.script_status ?? "pending"}</span>
                    </div>
                    <div className="meta-row">
                      <span>asset_id: {video.asset_id ?? "pending"}</span>
                      <span>{video.preview_approved_at ? `preview aprovada em ${video.preview_approved_at}` : "preview pendente"}</span>
                    </div>
                    <FileLinks apiBaseUrl={apiBaseUrl} video={video} />
                  </button>
                );
              })
            )}
          </div>
        </section>
      </section>

      <section className="panel detail-panel">
        <div className="panel-header">
          <h2>Detalhes do video selecionado</h2>
          <span className="panel-hint">{selectedVideo ? `Video #${selectedVideo.video_id}` : "Nenhum selecionado"}</span>
        </div>

        {selectedVideo ? (
          <div className="detail-grid">
            <div className="detail-summary">
              <div className="badges">
                <span className="badge">{selectedVideo.status}</span>
                <span className="badge accent">{selectedVideo.stage_status}</span>
                {selectedVideo.is_demo ? <span className="badge demo">DEMO / LOCAL</span> : null}
              </div>
              {selectedVideo.channel_slug ? (
                <p>
                  <strong>Canal:</strong> {selectedVideo.channel_slug}
                </p>
              ) : null}
              <p>
                <strong>Script:</strong> {selectedVideo.script_id ?? "pendente"} / {selectedVideo.script_status ?? "pendente"}
              </p>
              {selectedVideo.hook ? (
                <p>
                  <strong>Hook:</strong> {selectedVideo.hook}
                </p>
              ) : null}
              {selectedVideo.body_blocks?.length ? (
                <div className="detail-blocks">
                  <strong>Body:</strong>
                  <ul>
                    {selectedVideo.body_blocks.map((block, index) => (
                      <li key={`${selectedVideo.video_id}-block-${index}`}>{block}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {selectedVideo.call_to_action ? (
                <p>
                  <strong>CTA:</strong> {selectedVideo.call_to_action}
                </p>
              ) : null}
              {selectedVideo.estimated_duration_seconds ? (
                <p>
                  <strong>Duracao estimada:</strong> {selectedVideo.estimated_duration_seconds}s
                </p>
              ) : null}
              {selectedVideo.style_tone ? (
                <p>
                  <strong>Tom:</strong> {selectedVideo.style_tone}
                </p>
              ) : null}
              <p>
                <strong>Asset:</strong> {selectedVideo.asset_id ?? "pendente"}
              </p>
              {selectedVideo.asset_name || selectedVideo.asset_slug || selectedVideo.asset_type ? (
                <div className="detail-asset">
                  <p>
                    <strong>Asset atual:</strong> {selectedVideo.asset_name ?? selectedVideo.asset_slug ?? "sem nome"}
                  </p>
                  <p>
                    <strong>Slug:</strong> {selectedVideo.asset_slug ?? "pendente"}
                  </p>
                  <p>
                    <strong>Tipo:</strong> {selectedVideo.asset_type ?? "pendente"}
                  </p>
                  <p>
                    <strong>Grupo:</strong>{" "}
                    {selectedVideo.asset_channel_slug ?? selectedVideo.channel_slug ?? "sem canal"}
                  </p>
                  <p>
                    <strong>Tema:</strong> {selectedVideo.asset_topic ?? "pendente"}
                  </p>
                  <AssetTags tags={selectedVideo.asset_tags} />
                </div>
              ) : null}
            </div>

            <div className="script-editor">
              <div className="panel-header">
                <h3>Roteiro consolidado</h3>
                <span className="panel-hint">
                  {scriptEditable ? "Editavel antes do TTS" : "Bloqueado apos script aprovado"}
                </span>
              </div>
              <textarea
                value={scriptDraft}
                onChange={(event) => setScriptDraft(event.target.value)}
                disabled={!scriptEditable}
                placeholder="O roteiro consolidado aparece aqui antes do TTS."
                rows={10}
              />
              <div className="script-editor-actions">
                <button type="button" className="primary secondary" onClick={saveScriptDraft} disabled={!scriptEditable || busyAction !== null}>
                  {busyAction === "save-script" ? "Salvando..." : "Salvar roteiro"}
                </button>
                {!scriptEditable ? <p className="helper">A edicao fica liberada somente enquanto o video estiver em script_approved.</p> : null}
              </div>
            </div>

            <div className="stage-steps">
              <div className="panel-header">
                <h3>Controle por etapa</h3>
                <span className="panel-hint">stage atual: {selectedVideo.stage_status}</span>
              </div>
              <div className="stage-step-grid">
                <button
                  type="button"
                  onClick={() => void runPipelineStep("tts")}
                  disabled={busyAction !== null || !canRunStep(selectedVideo, "script_approved")}
                >
                  {busyAction === "tts" ? "Gerando..." : "Gerar TTS"}
                </button>
                <button
                  type="button"
                  onClick={() => void runPipelineStep("captions")}
                  disabled={busyAction !== null || !canRunStep(selectedVideo, "tts_done")}
                >
                  {busyAction === "captions" ? "Gerando..." : "Gerar captions"}
                </button>
                <button
                  type="button"
                  onClick={() => void runPipelineStep("asset")}
                  disabled={busyAction !== null || !canSelectAsset(selectedVideo)}
                >
                  {busyAction === "asset" ? "Selecionando..." : "Selecionar asset"}
                </button>
                <button
                  type="button"
                  onClick={() => void runPipelineStep("preview")}
                  disabled={busyAction !== null || !canRunStep(selectedVideo, "asset_ready")}
                >
                  {busyAction === "preview" ? "Gerando..." : "Gerar preview"}
                </button>
                <button
                  type="button"
                  onClick={() => void runPipelineStep("approve-preview")}
                  disabled={busyAction !== null || !canRunStep(selectedVideo, "preview_ready")}
                >
                  {busyAction === "approve-preview" ? "Aprovando..." : "Aprovar preview"}
                </button>
                <button
                  type="button"
                  onClick={() => void runPipelineStep("final")}
                  disabled={busyAction !== null || !canRunStep(selectedVideo, "preview_approved")}
                >
                  {busyAction === "final" ? "Renderizando..." : "Render final"}
                </button>
              </div>
              <p className="helper">
                Cada botao segue a ordem real do pipeline. Se o stage atual nao permitir a etapa, a API responde com erro claro.
              </p>
            </div>

            <div className="panel asset-panel">
              <div className="panel-header">
                <h3>Assets locais</h3>
                <div className="panel-actions">
                  <span className="panel-hint">{assets.length} itens</span>
                  <button type="button" className="ghost" onClick={() => void loadAssets()} disabled={busyAction !== null}>
                    Recarregar
                  </button>
                </div>
              </div>
              <p className="helper">
                Use um asset local antes do preview. O fallback padrao continua disponivel se nada for escolhido.
              </p>
              <div className="asset-list">
                {assets.length === 0 ? (
                  <div className="empty-state">Nenhum asset local cadastrado. O fallback padrao sera usado.</div>
                ) : (
                  assets.map((asset) => {
                    const isSelected = selectedVideo?.asset_id === asset.asset_id;
                    const isBusy = busyAction === `asset-${asset.asset_id}`;
                    const canUse = canSelectAsset(selectedVideo) || isSelected;
                    return (
                      <article key={asset.asset_id} className={`asset-card${isSelected ? " selected" : ""}`}>
                        <div className="video-card-top">
                          <div>
                            <p className="video-id">Asset #{asset.asset_id}</p>
                            <h3>{asset.name}</h3>
                          </div>
                          <div className="badges">
                            <span className="badge">{asset.asset_type}</span>
                            {asset.is_default ? <span className="badge demo">DEFAULT</span> : null}
                          </div>
                        </div>
                        <p className="helper">Slug: {asset.slug}</p>
                        <p className="helper">Arquivo: {asset.source_path ?? "sem caminho"}</p>
                        <p className="helper">Licenca: {asset.license_name}</p>
                        {asset.channel_slug ? <p className="helper">Canal: {asset.channel_slug}</p> : null}
                        {asset.topic ? <p className="helper">Tema: {asset.topic}</p> : null}
                        <AssetTags tags={asset.tags} />
                        <div className="asset-actions">
                          <button
                            type="button"
                            className="primary secondary"
                            onClick={() => void applyAsset(asset)}
                            disabled={!canUse || busyAction !== null || isSelected}
                          >
                            {isBusy ? "Aplicando..." : isSelected ? "Asset atual" : "Usar este asset"}
                          </button>
                        </div>
                      </article>
                    );
                  })
                )}
              </div>
            </div>

            <div className="paths">
              <PathLine label="audio_path" value={selectedVideo.audio_path} />
              <PathLine label="caption_path" value={selectedVideo.caption_path} />
              <PathLine label="asset_path" value={selectedVideo.asset_path} />
              <PathLine label="preview_path" value={selectedVideo.preview_path} />
              <PathLine label="final_path" value={selectedVideo.final_path} />
            </div>
          </div>
        ) : (
          <div className="empty-state">Selecione um video na lista para ver os paths gerados.</div>
        )}
      </section>
    </main>
  );
}
