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
  visual_template?: string | null;
  target_duration_seconds?: number | null;
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

type ChannelPresetItem = {
  channel_slug: string;
  channel_name: string;
  default_topic_style?: string | null;
  default_visual_template?: string;
  default_asset_slug?: string | null;
  default_cta?: string | null;
  target_duration_seconds?: number | null;
};

type ChannelPresetListResponse = {
  items: ChannelPresetItem[];
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

const DEFAULT_ASSET_FORM = {
  filePath: "storage/assets/manual/python-bg.png",
  name: "Python Background",
  slug: "python-background",
  licenseName: "generated-local",
  channelSlug: "",
  topic: "",
  tagsText: "python, background",
};

const DEFAULT_VISUAL_TEMPLATE = "default";

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
  const [channelPresets, setChannelPresets] = useState<ChannelPresetItem[]>([]);
  const [selectedVideoId, setSelectedVideoId] = useState<number | null>(null);
  const selectedVideoIdRef = useRef<number | null>(null);
  const channelSlugRef = useRef(DEFAULT_FORM.channelSlug);
  const [scriptDraft, setScriptDraft] = useState("");
  const [selectedVisualTemplate, setSelectedVisualTemplate] = useState(DEFAULT_VISUAL_TEMPLATE);
  const [pendingAssetId, setPendingAssetId] = useState<number | null>(null);
  const [presetChannelName, setPresetChannelName] = useState("");
  const [presetDefaultTopicStyle, setPresetDefaultTopicStyle] = useState("");
  const [presetDefaultVisualTemplate, setPresetDefaultVisualTemplate] = useState(DEFAULT_VISUAL_TEMPLATE);
  const [presetDefaultAssetSlug, setPresetDefaultAssetSlug] = useState("");
  const [presetDefaultCta, setPresetDefaultCta] = useState("");
  const [presetTargetDurationSeconds, setPresetTargetDurationSeconds] = useState("");
  const [presetNotice, setPresetNotice] = useState("");
  const [assetFilePath, setAssetFilePath] = useState(DEFAULT_ASSET_FORM.filePath);
  const [assetName, setAssetName] = useState(DEFAULT_ASSET_FORM.name);
  const [assetSlug, setAssetSlug] = useState(DEFAULT_ASSET_FORM.slug);
  const [assetLicenseName, setAssetLicenseName] = useState(DEFAULT_ASSET_FORM.licenseName);
  const [assetChannelSlug, setAssetChannelSlug] = useState(DEFAULT_ASSET_FORM.channelSlug);
  const [assetTopic, setAssetTopic] = useState(DEFAULT_ASSET_FORM.topic);
  const [assetTagsText, setAssetTagsText] = useState(DEFAULT_ASSET_FORM.tagsText);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<MessageState>({ kind: "idle", text: "" });

  const selectedVideo = useMemo(
    () => videos.find((video) => video.video_id === selectedVideoId) ?? null,
    [selectedVideoId, videos],
  );
  const activeChannelPreset = useMemo(
    () => channelPresets.find((preset) => preset.channel_slug === channelSlug.trim()) ?? null,
    [channelPresets, channelSlug],
  );
  const selectedVideoVisualTemplate = selectedVideo?.visual_template ?? DEFAULT_VISUAL_TEMPLATE;
  const scriptEditable = selectedVideo?.stage_status === "script_approved";
  const pipelineCompleted =
    selectedVideo?.stage_status === "final_rendered" || selectedVideo?.status === "completed";
  const previewNeedsRefresh = Boolean(
    selectedVideo &&
      selectedVideo.preview_path &&
      selectedVideo.stage_status !== "final_rendered" &&
      selectedVideo.status !== "completed" &&
      (pendingAssetId !== null || selectedVisualTemplate !== selectedVideoVisualTemplate),
  );

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

  function canChangeTemplate(video: VideoItem | null) {
    return Boolean(video && video.stage_status !== "final_rendered" && video.status !== "completed");
  }

  function canRegeneratePreview(video: VideoItem | null) {
    return Boolean(
      video &&
        video.audio_path &&
        video.caption_path &&
        video.asset_path &&
        video.stage_status !== "final_rendered" &&
        video.status !== "completed",
    );
  }

  function parseTagsInput(value: string) {
    return value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function formatTargetDuration(value: number | null | undefined) {
    return value ? `${value}s` : "opcional";
  }

  const applyPresetToForm = useCallback((preset: ChannelPresetItem | null) => {
    if (!preset) {
      setPresetChannelName("");
      setPresetDefaultTopicStyle("");
      setPresetDefaultVisualTemplate(DEFAULT_VISUAL_TEMPLATE);
      setPresetDefaultAssetSlug("");
      setPresetDefaultCta("");
      setPresetTargetDurationSeconds("");
      setPresetNotice("");
      return;
    }

    setPresetChannelName(preset.channel_name);
    setPresetDefaultTopicStyle(preset.default_topic_style ?? "");
    setPresetDefaultVisualTemplate(preset.default_visual_template ?? DEFAULT_VISUAL_TEMPLATE);
    setPresetDefaultAssetSlug(preset.default_asset_slug ?? "");
    setPresetDefaultCta(preset.default_cta ?? "");
    setPresetTargetDurationSeconds(preset.target_duration_seconds ? String(preset.target_duration_seconds) : "");
    setPresetNotice("Preset encontrado para este canal");
  }, []);

  useEffect(() => {
    apiBaseUrlRef.current = apiBaseUrl;
  }, [apiBaseUrl]);

  useEffect(() => {
    selectedVideoIdRef.current = selectedVideoId;
  }, [selectedVideoId]);

  useEffect(() => {
    channelSlugRef.current = channelSlug;
  }, [channelSlug]);

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
      const nextSelectedVideo = items.find((item) => item.video_id === nextSelectedId) ?? null;
      setScriptDraft(buildScriptDraft(nextSelectedVideo));
      setSelectedVisualTemplate(nextSelectedVideo?.visual_template ?? DEFAULT_VISUAL_TEMPLATE);
      setPendingAssetId(null);
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

  const loadChannelPresets = useCallback(async (options?: { baseUrl?: string; quiet?: boolean; channelSlug?: string }) => {
    const baseUrl = options?.baseUrl ?? apiBaseUrlRef.current;
    const quiet = options?.quiet ?? false;
    const targetChannelSlug = (options?.channelSlug ?? channelSlugRef.current).trim();
    try {
      const payload = await requestJson<ChannelPresetListResponse>(baseUrl, "/internal/videos/channel-presets");
      const items = payload.items ?? [];
      setChannelPresets(items);
      applyPresetToForm(items.find((preset) => preset.channel_slug === targetChannelSlug) ?? null);
      if (!quiet) {
        setMessage({ kind: "success", text: `Foram carregados ${items.length} presets de canal.` });
      }
    } catch (error) {
      if (!quiet) {
        setMessage({ kind: "error", text: error instanceof Error ? error.message : "Falha ao carregar presets." });
      }
    }
  }, [applyPresetToForm]);

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
    setSelectedVisualTemplate(nextVideo.visual_template ?? DEFAULT_VISUAL_TEMPLATE);
    setPendingAssetId(null);
  }

  function selectVideo(video: VideoItem) {
    setSelectedVideoId(video.video_id);
    selectedVideoIdRef.current = video.video_id;
    setScriptDraft(buildScriptDraft(video));
    setSelectedVisualTemplate(video.visual_template ?? DEFAULT_VISUAL_TEMPLATE);
    setPendingAssetId(null);
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
          visual_template: selectedVisualTemplate,
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

  async function applyAsset(asset: AssetItem, options?: { quiet?: boolean }) {
    if (selectedVideoId === null) {
      const error = new Error("Selecione um video antes de escolher um asset.");
      if (options?.quiet) {
        throw error;
      }
      setMessage({ kind: "error", text: error.message });
      return;
    }
    if (canSelectAsset(selectedVideo)) {
      setBusyAction(`asset-${asset.asset_id}`);
      try {
        const updated = await requestJson<VideoItem>(apiBaseUrl, `/internal/videos/${selectedVideoId}/asset`, {
          method: "POST",
          body: JSON.stringify({
            asset_id: asset.asset_id,
          }),
        });
        mergeVideo(updated);
        setPendingAssetId(null);
        if (!options?.quiet) {
          setMessage({ kind: "success", text: `Asset ${asset.name} aplicado ao video ${selectedVideoId}.` });
        }
        void loadVideos({ quiet: true });
        void loadAssets({ quiet: true });
      } catch (error) {
        if (options?.quiet) {
          throw error;
        }
        setMessage({ kind: "error", text: error instanceof Error ? error.message : "Falha ao aplicar asset." });
      } finally {
        setBusyAction(null);
      }
      return;
    }

    if (!canRegeneratePreview(selectedVideo)) {
      const error = new Error("Asset so pode ser trocado antes do preview, depois das captions.");
      if (options?.quiet) {
        throw error;
      }
      setMessage({ kind: "error", text: error.message });
      return;
    }

    setPendingAssetId(asset.asset_id);
    if (!options?.quiet) {
      setMessage({
        kind: "success",
        text: `Asset ${asset.name} selecionado para regeneracao do preview do video ${selectedVideoId}.`,
      });
    }
  }

  async function registerLocalAsset() {
    setBusyAction("register-asset");
    try {
      const created = await requestJson<AssetItem>(apiBaseUrl, "/internal/videos/assets/register-local", {
        method: "POST",
        body: JSON.stringify({
          file_path: assetFilePath,
          name: assetName,
          slug: assetSlug,
          asset_type: "background_image",
          license_name: assetLicenseName,
          channel_slug: assetChannelSlug || undefined,
          topic: assetTopic || undefined,
          tags: parseTagsInput(assetTagsText),
        }),
      });
      await loadAssets({ quiet: true });
      if (selectedVideoId !== null && canSelectAsset(selectedVideo)) {
        try {
          await applyAsset(created, { quiet: true });
          setMessage({
            kind: "success",
            text: "Asset cadastrado. Asset aplicado ao vídeo atual.",
          });
          return;
        } catch (error) {
          setMessage({
            kind: "error",
            text:
              error instanceof Error
                ? `Asset cadastrado, mas não foi possível aplicar ao vídeo atual: ${error.message}`
                : "Asset cadastrado, mas não foi possível aplicar ao vídeo atual.",
          });
          return;
        }
      }
      if (selectedVideoId !== null && canRegeneratePreview(selectedVideo)) {
        setPendingAssetId(created.asset_id);
        setMessage({
          kind: "success",
          text: "Asset cadastrado. Asset selecionado para regeneracao do preview.",
        });
        return;
      }
      setMessage({ kind: "success", text: "Asset cadastrado." });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "Falha ao cadastrar asset local." });
    } finally {
      setBusyAction(null);
    }
  }

  async function saveChannelPreset() {
    if (!channelSlug.trim()) {
      setMessage({ kind: "error", text: "Informe um channel_slug antes de salvar o preset." });
      return;
    }
    if (!presetChannelName.trim()) {
      setMessage({ kind: "error", text: "Informe o nome do canal antes de salvar o preset." });
      return;
    }

    const parsedDuration = presetTargetDurationSeconds.trim() ? Number(presetTargetDurationSeconds) : null;
    if (parsedDuration !== null && (!Number.isInteger(parsedDuration) || parsedDuration <= 0)) {
      setMessage({ kind: "error", text: "A duracao alvo precisa ser um inteiro positivo." });
      return;
    }

    setBusyAction("save-preset");
    try {
      const savedPreset = await requestJson<ChannelPresetItem>(apiBaseUrl, "/internal/videos/channel-presets", {
        method: "POST",
        body: JSON.stringify({
          channel_slug: channelSlug,
          channel_name: presetChannelName,
          default_topic_style: presetDefaultTopicStyle || undefined,
          default_visual_template: presetDefaultVisualTemplate,
          default_asset_slug: presetDefaultAssetSlug || undefined,
          default_cta: presetDefaultCta || undefined,
          target_duration_seconds: parsedDuration ?? undefined,
        }),
      });
      setChannelSlug(savedPreset.channel_slug);
      setChannelName(savedPreset.channel_name);
      applyPresetToForm(savedPreset);
      await loadChannelPresets({ quiet: true, channelSlug: savedPreset.channel_slug });
      setMessage({ kind: "success", text: `Preset do canal ${savedPreset.channel_slug} salvo com sucesso.` });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "Falha ao salvar preset do canal." });
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
      const payload =
        step === "preview"
          ? { visual_template: selectedVisualTemplate }
          : stepModes[step]
            ? { execution_mode: "fake" }
            : undefined;
      const updated = await requestJson<VideoItem>(apiBaseUrl, stepPaths[step], {
        method: "POST",
        body: payload ? JSON.stringify(payload) : undefined,
      });
      mergeVideo(updated);
      setScriptDraft(buildScriptDraft(updated));
      setSelectedVisualTemplate(updated.visual_template ?? DEFAULT_VISUAL_TEMPLATE);
      setMessage({ kind: "success", text: `${stepLabels[step]} executado com sucesso.` });
      void loadVideos({ quiet: true });
      void loadAssets({ quiet: true });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : `Falha ao executar ${stepLabels[step]}.` });
    } finally {
      setBusyAction(null);
    }
  }

  async function regeneratePreview() {
    if (selectedVideoId === null || selectedVideo === null) {
      setMessage({ kind: "error", text: "Selecione um video antes de regenerar o preview." });
      return;
    }
    if (!canRegeneratePreview(selectedVideo)) {
      setMessage({
        kind: "error",
        text: "Preview so pode ser regenerado depois de audio, captions e asset estarem disponiveis.",
      });
      return;
    }

    setBusyAction("regenerate-preview");
    try {
      const updated = await requestJson<VideoItem>(apiBaseUrl, `/internal/videos/${selectedVideoId}/preview/regenerate`, {
        method: "POST",
        body: JSON.stringify({
          asset_id: pendingAssetId ?? undefined,
          visual_template: selectedVisualTemplate,
        }),
      });
      mergeVideo(updated);
      setPendingAssetId(null);
      setMessage({ kind: "success", text: `Preview regenerado com sucesso para o video ${selectedVideoId}.` });
      void loadVideos({ quiet: true });
      void loadAssets({ quiet: true });
    } catch (error) {
      setMessage({
        kind: "error",
        text: error instanceof Error ? error.message : "Falha ao regenerar o preview.",
      });
    } finally {
      setBusyAction(null);
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadVideos();
      void loadAssets({ quiet: true });
      void loadChannelPresets({ quiet: true });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadVideos, loadAssets, loadChannelPresets]);

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
                void loadChannelPresets({ quiet: true });
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
              <input
                value={channelSlug}
                onChange={(event) => {
                  const nextChannelSlug = event.target.value;
                  setChannelSlug(nextChannelSlug);
                  applyPresetToForm(channelPresets.find((preset) => preset.channel_slug === nextChannelSlug.trim()) ?? null);
                }}
              />
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
            <h2>Presets do canal</h2>
            <span className="panel-hint">{channelPresets.length} itens salvos</span>
          </div>
          {presetNotice ? <div className="preset-notice success">{presetNotice}</div> : null}
          {activeChannelPreset ? (
            <div className="detail-asset">
              <p>
                <strong>Preset ativo:</strong> {activeChannelPreset.channel_slug}
              </p>
              <p>
                <strong>Canal:</strong> {activeChannelPreset.channel_name}
              </p>
              <p>
                <strong>Template:</strong> {activeChannelPreset.default_visual_template ?? DEFAULT_VISUAL_TEMPLATE}
              </p>
              <p>
                <strong>Asset padrao:</strong> {activeChannelPreset.default_asset_slug ?? "nenhum"}
              </p>
              <p>
                <strong>CTA padrao:</strong> {activeChannelPreset.default_cta ?? "nenhum"}
              </p>
              <p>
                <strong>Duracao alvo:</strong> {formatTargetDuration(activeChannelPreset.target_duration_seconds)}
              </p>
              <p>
                <strong>Tom/estilo:</strong> {activeChannelPreset.default_topic_style ?? "padrao"}
              </p>
            </div>
          ) : (
            <p className="helper">Nenhum preset ativo para o channel_slug atual.</p>
          )}
          <div className="asset-form">
            <div className="asset-form-grid">
              <label className="field">
                <span>Nome do canal</span>
                <input value={presetChannelName} onChange={(event) => setPresetChannelName(event.target.value)} />
              </label>
              <label className="field">
                <span>Tom/estilo padrao</span>
                <input value={presetDefaultTopicStyle} onChange={(event) => setPresetDefaultTopicStyle(event.target.value)} />
              </label>
              <label className="field">
                <span>Template visual padrao</span>
                <select value={presetDefaultVisualTemplate} onChange={(event) => setPresetDefaultVisualTemplate(event.target.value)}>
                  <option value="default">default</option>
                  <option value="dark_overlay">dark_overlay</option>
                  <option value="big_captions">big_captions</option>
                </select>
              </label>
              <label className="field">
                <span>Asset padrao slug</span>
                <input value={presetDefaultAssetSlug} onChange={(event) => setPresetDefaultAssetSlug(event.target.value)} />
              </label>
              <label className="field">
                <span>CTA padrao</span>
                <input value={presetDefaultCta} onChange={(event) => setPresetDefaultCta(event.target.value)} />
              </label>
              <label className="field">
                <span>Duracao alvo em segundos</span>
                <input
                  inputMode="numeric"
                  value={presetTargetDurationSeconds}
                  onChange={(event) => setPresetTargetDurationSeconds(event.target.value)}
                />
              </label>
            </div>
            <div className="asset-form-actions">
              <span className="panel-hint">Salvo em storage/config/channel-presets</span>
              <button type="button" className="primary secondary" onClick={() => void saveChannelPreset()} disabled={busyAction !== null}>
                {busyAction === "save-preset" ? "Salvando..." : "Salvar preset"}
              </button>
            </div>
          </div>

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
                        <span className="badge subtle">template: {video.visual_template ?? DEFAULT_VISUAL_TEMPLATE}</span>
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
              {selectedVideo.target_duration_seconds ? (
                <p>
                  <strong>Duracao alvo:</strong> {selectedVideo.target_duration_seconds}s
                </p>
              ) : null}
              {selectedVideo.style_tone ? (
                <p>
                  <strong>Tom:</strong> {selectedVideo.style_tone}
                </p>
              ) : null}
              <p>
                <strong>Template visual atual:</strong> {selectedVideo.visual_template ?? DEFAULT_VISUAL_TEMPLATE}
              </p>
              {previewNeedsRefresh ? (
                <p>
                  <strong>Template selecionado:</strong> {selectedVisualTemplate}
                </p>
              ) : null}
              <p>
                <strong>Asset:</strong> {selectedVideo.asset_id ?? "pendente"}
              </p>
              {pendingAssetId !== null ? (
                <p>
                  <strong>Asset selecionado para regenerar:</strong>{" "}
                  {assets.find((asset) => asset.asset_id === pendingAssetId)?.name ?? `#${pendingAssetId}`}
                </p>
              ) : null}
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
              <div className="template-picker">
                <label className="field">
                  <span>Template visual</span>
                  <select
                    value={selectedVisualTemplate}
                    onChange={(event) => setSelectedVisualTemplate(event.target.value)}
                    disabled={!canChangeTemplate(selectedVideo) || busyAction !== null}
                  >
                    <option value="default">default</option>
                    <option value="dark_overlay">dark_overlay</option>
                    <option value="big_captions">big_captions</option>
                  </select>
                </label>
                <p className="helper">
                  O template altera apenas preview/final. Depois do final render, a troca fica bloqueada.
                </p>
                {previewNeedsRefresh ? (
                  <p className="warning">
                    Ha mudancas visuais pendentes. Regenerar preview para aplicar o asset/template selecionado.
                  </p>
                ) : null}
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
                  onClick={() => void regeneratePreview()}
                  disabled={busyAction !== null || !canRegeneratePreview(selectedVideo) || !selectedVideo?.preview_path}
                >
                  {busyAction === "regenerate-preview" ? "Regenerando..." : "Regenerar preview"}
                </button>
                <button
                  type="button"
                  onClick={() => void runPipelineStep("approve-preview")}
                  disabled={busyAction !== null || !canRunStep(selectedVideo, "preview_ready") || previewNeedsRefresh}
                >
                  {busyAction === "approve-preview" ? "Aprovando..." : "Aprovar preview"}
                </button>
                <button
                  type="button"
                  onClick={() => void runPipelineStep("final")}
                  disabled={busyAction !== null || !canRunStep(selectedVideo, "preview_approved") || previewNeedsRefresh}
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
              {previewNeedsRefresh ? (
                <p className="warning">
                  O asset ou template atual foi alterado. Use {'"'}Regenerar preview{'"'} para atualizar o video selecionado.
                </p>
              ) : null}
              <div className="asset-form">
                <div className="asset-form-grid">
                  <label className="field">
                    <span>File path</span>
                    <input value={assetFilePath} onChange={(event) => setAssetFilePath(event.target.value)} />
                  </label>
                  <label className="field">
                    <span>Nome</span>
                    <input value={assetName} onChange={(event) => setAssetName(event.target.value)} />
                  </label>
                  <label className="field">
                    <span>Slug</span>
                    <input value={assetSlug} onChange={(event) => setAssetSlug(event.target.value)} />
                  </label>
                  <label className="field">
                    <span>Licenca</span>
                    <input value={assetLicenseName} onChange={(event) => setAssetLicenseName(event.target.value)} />
                  </label>
                  <label className="field">
                    <span>Channel slug opcional</span>
                    <input value={assetChannelSlug} onChange={(event) => setAssetChannelSlug(event.target.value)} />
                  </label>
                  <label className="field">
                    <span>Tema/nicho opcional</span>
                    <input value={assetTopic} onChange={(event) => setAssetTopic(event.target.value)} />
                  </label>
                  <label className="field asset-form-tags">
                    <span>Tags opcional</span>
                    <input value={assetTagsText} onChange={(event) => setAssetTagsText(event.target.value)} />
                  </label>
                </div>
                <div className="asset-form-actions">
                  <span className="panel-hint">asset_type: background_image</span>
                  <button type="button" className="primary secondary" onClick={() => void registerLocalAsset()} disabled={busyAction !== null}>
                    {busyAction === "register-asset" ? "Cadastrando..." : "Cadastrar asset"}
                  </button>
                </div>
                <p className="helper">
                  Exemplo pronto para a UI: <code>storage/assets/manual/python-bg.png</code>. Arquivos .mp4 ainda sao bloqueados.
                </p>
              </div>
              <div className="asset-list">
                {assets.length === 0 ? (
                  <div className="empty-state">Nenhum asset local cadastrado. O fallback padrao sera usado.</div>
                ) : (
                  assets.map((asset) => {
                    const isSelected = selectedVideo?.asset_id === asset.asset_id;
                    const isPending = pendingAssetId === asset.asset_id;
                    const isBusy = busyAction === `asset-${asset.asset_id}`;
                    const canUse = canSelectAsset(selectedVideo) || canRegeneratePreview(selectedVideo);
                    return (
                      <article
                        key={asset.asset_id}
                        className={`asset-card${isSelected ? " selected" : ""}${isPending ? " pending" : ""}`}
                      >
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
                            disabled={!canUse || busyAction !== null || (isSelected && !isPending)}
                          >
                            {isBusy
                              ? "Aplicando..."
                              : isPending
                                ? "Selecionado para regenerar"
                                : isSelected
                                  ? "Asset atual"
                                  : canSelectAsset(selectedVideo)
                                    ? "Usar este asset"
                                    : "Selecionar para regenerar"}
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
