"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type VideoItem = {
  video_id: number;
  video_slug?: string | null;
  status: string;
  stage_status: string;
  script_id?: number | null;
  script_status?: string | null;
  asset_id?: number | null;
  audio_path?: string | null;
  caption_path?: string | null;
  preview_path?: string | null;
  final_path?: string | null;
  asset_path?: string | null;
  preview_approved_at?: string | null;
};

type VideoListResponse = {
  items: VideoItem[];
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

export default function DashboardPage() {
  const [apiBaseUrl, setApiBaseUrl] = useState(DEFAULT_API_BASE_URL);
  const apiBaseUrlRef = useRef(DEFAULT_API_BASE_URL);
  const [topic, setTopic] = useState(DEFAULT_FORM.topic);
  const [channelSlug, setChannelSlug] = useState(DEFAULT_FORM.channelSlug);
  const [channelName, setChannelName] = useState(DEFAULT_FORM.channelName);
  const [videoTitle, setVideoTitle] = useState(DEFAULT_FORM.videoTitle);
  const [videos, setVideos] = useState<VideoItem[]>([]);
  const [selectedVideoId, setSelectedVideoId] = useState<number | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<MessageState>({ kind: "idle", text: "" });

  const selectedVideo = useMemo(
    () => videos.find((video) => video.video_id === selectedVideoId) ?? null,
    [selectedVideoId, videos],
  );

  useEffect(() => {
    apiBaseUrlRef.current = apiBaseUrl;
  }, [apiBaseUrl]);

  const loadVideos = useCallback(async (nextBaseUrl?: string) => {
    const baseUrl = nextBaseUrl ?? apiBaseUrlRef.current;
    setLoading(true);
    try {
      const payload = await requestJson<VideoListResponse>(baseUrl, "/internal/videos");
      const items = payload.items ?? [];
      setVideos(items);
      setSelectedVideoId((current) => {
        if (current !== null && items.some((item) => item.video_id === current)) {
          return current;
        }
        return items[0]?.video_id ?? null;
      });
      setMessage({ kind: "success", text: `Foram carregados ${items.length} videos.` });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "Falha ao carregar videos." });
    } finally {
      setLoading(false);
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
      await loadVideos();
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
      const produced = await requestJson<VideoItem>(apiBaseUrl, `/internal/videos/${selectedVideoId}/produce`, {
        method: "POST",
        body: JSON.stringify({
          auto_approve_preview: true,
          execution_mode: "fake",
        }),
      });
      mergeVideo(produced);
      setMessage({ kind: "success", text: `Pipeline concluido para o video ${selectedVideoId}.` });
      await loadVideos();
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

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadVideos();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadVideos]);

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
            <button type="button" onClick={() => void loadVideos()} disabled={loading}>
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
          <button type="button" className="primary secondary" onClick={produceFakePipeline} disabled={busyAction !== null}>
            {busyAction === "produce" ? "Processando..." : "Produzir pipeline fake"}
          </button>

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
                    onClick={() => setSelectedVideoId(video.video_id)}
                  >
                    <div className="video-card-top">
                      <div>
                        <p className="video-id">Video #{video.video_id}</p>
                        <h3>{video.video_slug ?? `video-${video.video_id}`}</h3>
                      </div>
                      <div className="badges">
                        <span className="badge">{video.status}</span>
                        <span className="badge accent">{video.stage_status}</span>
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
              </div>
              <p>
                <strong>Script:</strong> {selectedVideo.script_id ?? "pendente"} / {selectedVideo.script_status ?? "pendente"}
              </p>
              <p>
                <strong>Asset:</strong> {selectedVideo.asset_id ?? "pendente"}
              </p>
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
