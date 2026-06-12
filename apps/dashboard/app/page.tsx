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
  video_title?: string | null;
  content_brain_context_used?: boolean;
  winning_signals_count?: number;
  weak_signals_count?: number;
  applied_reason_tags?: string[] | null;
  export_package_dir?: string | null;
  export_metadata_path?: string | null;
  export_final_path?: string | null;
  export_preview_path?: string | null;
  export_caption_path?: string | null;
  youtube_publish_path?: string | null;
  youtube_publish_title?: string | null;
  youtube_publish_description?: string | null;
  youtube_publish_tags?: string[] | null;
  youtube_publish_visibility?: string | null;
  youtube_publish_made_for_kids?: boolean | null;
  performance_label?: string | null;
  performance_notes?: string | null;
  performance_reason_tags?: string[] | null;
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

type VideoJobItem = {
  job_id: string;
  video_id: number;
  job_type: string;
  status: string;
  error_message?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  visual_template?: string | null;
};

type PublishReadinessCheckItem = {
  key: string;
  label: string;
  ready: boolean;
  value?: string | null;
};

type PublishReadinessResponse = {
  video_id: number;
  video_slug?: string | null;
  channel_slug?: string | null;
  stage_status?: string | null;
  overall_status: string;
  ready: boolean;
  missing_items: string[];
  items: PublishReadinessCheckItem[];
};

type ContentBrainSignalItem = {
  video_id: number;
  video_slug?: string | null;
  channel_slug?: string | null;
  topic?: string | null;
  performance_label?: string | null;
  notes?: string | null;
  reason_tags?: string[] | null;
  updated_at?: string | null;
};

type ContentBrainSignalListResponse = {
  items: ContentBrainSignalItem[];
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

const DEFAULT_UPLOAD_FORM = {
  licenseName: "generated-local",
  channelSlug: "",
  topic: "",
  tagsText: "",
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
    { label: "Metadata export", path: video.export_metadata_path },
    { label: "Final export", path: video.export_final_path },
    { label: "Captions export", path: video.export_caption_path },
    { label: "Preview export", path: video.export_preview_path },
    { label: "YouTube prep", path: video.youtube_publish_path },
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
  const [contentBrainSignals, setContentBrainSignals] = useState<ContentBrainSignalItem[]>([]);
  const [latestJob, setLatestJob] = useState<VideoJobItem | null>(null);
  const [publishReadiness, setPublishReadiness] = useState<PublishReadinessResponse | null>(null);
  const [selectedVideoId, setSelectedVideoId] = useState<number | null>(null);
  const selectedVideoIdRef = useRef<number | null>(null);
  const channelSlugRef = useRef(DEFAULT_FORM.channelSlug);
  const [scriptDraft, setScriptDraft] = useState("");
  const [selectedVisualTemplate, setSelectedVisualTemplate] = useState(DEFAULT_VISUAL_TEMPLATE);
  const [youtubeTitle, setYoutubeTitle] = useState("");
  const [youtubeDescription, setYoutubeDescription] = useState("");
  const [youtubeTagsText, setYoutubeTagsText] = useState("");
  const [youtubeVisibility, setYoutubeVisibility] = useState("private");
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
  const [assetUploadFile, setAssetUploadFile] = useState<File | null>(null);
  const [assetUploadName, setAssetUploadName] = useState("");
  const [assetUploadSlug, setAssetUploadSlug] = useState("");
  const [assetUploadLicenseName, setAssetUploadLicenseName] = useState(DEFAULT_UPLOAD_FORM.licenseName);
  const [assetUploadChannelSlug, setAssetUploadChannelSlug] = useState(DEFAULT_UPLOAD_FORM.channelSlug);
  const [assetUploadTopic, setAssetUploadTopic] = useState(DEFAULT_UPLOAD_FORM.topic);
  const [assetUploadTagsText, setAssetUploadTagsText] = useState(DEFAULT_UPLOAD_FORM.tagsText);
  const [performanceFilter, setPerformanceFilter] = useState("all");
  const [performanceLabel, setPerformanceLabel] = useState("unknown");
  const [performanceNotes, setPerformanceNotes] = useState("");
  const [performanceReasonTagsText, setPerformanceReasonTagsText] = useState("");
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<MessageState>({ kind: "idle", text: "" });

  const selectedVideo = useMemo(
    () => videos.find((video) => video.video_id === selectedVideoId) ?? null,
    [selectedVideoId, videos],
  );
  const filteredVideos = useMemo(
    () =>
      videos.filter((video) => {
        if (performanceFilter === "all") {
          return true;
        }
        return (video.performance_label ?? "unknown") === performanceFilter;
      }),
    [performanceFilter, videos],
  );
  const activeChannelPreset = useMemo(
    () => channelPresets.find((preset) => preset.channel_slug === channelSlug.trim()) ?? null,
    [channelPresets, channelSlug],
  );
  const contentBrainWinningCount = useMemo(
    () => contentBrainSignals.filter((signal) => signal.performance_label === "winning").length,
    [contentBrainSignals],
  );
  const contentBrainWeakCount = useMemo(
    () => contentBrainSignals.filter((signal) => signal.performance_label === "weak").length,
    [contentBrainSignals],
  );
  const selectedVideoVisualTemplate = selectedVideo?.visual_template ?? DEFAULT_VISUAL_TEMPLATE;
  const selectedVideoPerformanceLabel = selectedVideo?.performance_label ?? "unknown";
  const scriptEditable = selectedVideo?.stage_status === "script_approved";
  const pipelineCompleted =
    selectedVideo?.stage_status === "final_rendered" || selectedVideo?.status === "completed";
  const exportPackageReady = Boolean(selectedVideo && selectedVideo.stage_status === "final_rendered");
  const youtubePrepReady = Boolean(selectedVideo && selectedVideo.stage_status === "final_rendered");
  const publishReady = publishReadiness?.overall_status === "ready";
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

  function buildPerformanceReasonTagsText(video: VideoItem | null) {
    if (!video?.performance_reason_tags?.length) {
      return "";
    }
    return video.performance_reason_tags.join(", ");
  }

  function buildYoutubePrepDraft(video: VideoItem | null) {
    if (!video) {
      return {
        title: "",
        description: "",
        tagsText: "",
        visibility: "private",
      };
    }

    const title = video.youtube_publish_title ?? video.video_title ?? video.video_slug ?? "Video Shorts";
    const description =
      video.youtube_publish_description ??
      [video.hook, ...(video.body_blocks ?? []), video.call_to_action, video.style_tone ? `Tom: ${video.style_tone}` : null]
        .filter(Boolean)
        .join("\n\n");
    const tags =
      video.youtube_publish_tags?.length
        ? video.youtube_publish_tags
        : [
            video.channel_slug,
            video.asset_channel_slug,
            video.asset_slug,
            ...(video.asset_tags ?? []),
            ...(video.performance_reason_tags ?? []),
            ...(video.applied_reason_tags ?? []),
          ]
            .filter(Boolean)
            .map((item) => String(item).trim())
            .filter(Boolean);
    const uniqueTags = Array.from(new Set(tags));

    return {
      title,
      description,
      tagsText: uniqueTags.join(", "),
      visibility: video.youtube_publish_visibility ?? "private",
    };
  }

  const syncPerformanceForm = useCallback((video: VideoItem | null) => {
    setPerformanceLabel(video?.performance_label ?? "unknown");
    setPerformanceNotes(video?.performance_notes ?? "");
    setPerformanceReasonTagsText(buildPerformanceReasonTagsText(video));
  }, []);

  const syncYoutubePrepForm = useCallback((video: VideoItem | null) => {
    const draft = buildYoutubePrepDraft(video);
    setYoutubeTitle(draft.title);
    setYoutubeDescription(draft.description);
    setYoutubeTagsText(draft.tagsText);
    setYoutubeVisibility(draft.visibility);
  }, []);

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

  function parseReasonTagsInput(value: string) {
    return parseTagsInput(value);
  }

  function sanitizeUploadStem(value: string) {
    return value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "asset";
  }

  function isAllowedUploadExtension(fileName: string) {
    const extension = fileName.slice(fileName.lastIndexOf(".")).toLowerCase();
    return [".png", ".jpg", ".jpeg", ".webp"].includes(extension);
  }

  function resetUploadForm() {
    setAssetUploadFile(null);
    setAssetUploadName("");
    setAssetUploadSlug("");
    setAssetUploadLicenseName(DEFAULT_UPLOAD_FORM.licenseName);
    setAssetUploadChannelSlug(DEFAULT_UPLOAD_FORM.channelSlug);
    setAssetUploadTopic(DEFAULT_UPLOAD_FORM.topic);
    setAssetUploadTagsText(DEFAULT_UPLOAD_FORM.tagsText);
  }

  function formatTargetDuration(value: number | null | undefined) {
    return value ? `${value}s` : "opcional";
  }

  function formatJobTimestamp(value?: string | null) {
    if (!value) {
      return "pendente";
    }
    return new Date(value).toLocaleString("pt-BR");
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

  const loadLatestJob = useCallback(async (videoId: number | null, options?: { baseUrl?: string; quiet?: boolean }) => {
    if (videoId === null) {
      setLatestJob(null);
      return;
    }
    const baseUrl = options?.baseUrl ?? apiBaseUrlRef.current;
    const quiet = options?.quiet ?? false;
    try {
      const payload = await requestJson<VideoJobItem>(baseUrl, `/internal/videos/${videoId}/jobs/latest`);
      setLatestJob(payload);
      if (!quiet) {
        setMessage({ kind: "success", text: `Job ${payload.job_id} atualizado para o video ${videoId}.` });
      }
    } catch (error) {
      setLatestJob(null);
      const text = error instanceof Error ? error.message : "Falha ao carregar job.";
      if (!quiet && !text.includes("Job not found")) {
        setMessage({ kind: "error", text });
      }
    }
  }, []);

  const loadContentBrainSignals = useCallback(async (options?: { baseUrl?: string; quiet?: boolean }) => {
    const baseUrl = options?.baseUrl ?? apiBaseUrlRef.current;
    const quiet = options?.quiet ?? false;
    try {
      const payload = await requestJson<ContentBrainSignalListResponse>(baseUrl, "/internal/videos/content-brain/signals");
      const items = payload.items ?? [];
      setContentBrainSignals(items);
      if (!quiet) {
        setMessage({ kind: "success", text: `Foram carregados ${items.length} sinais do ContentBrain local.` });
      }
    } catch (error) {
      if (!quiet) {
        setMessage({ kind: "error", text: error instanceof Error ? error.message : "Falha ao carregar sinais do ContentBrain." });
      }
    }
  }, []);

  const loadPublishReadiness = useCallback(async (videoId: number | null, options?: { baseUrl?: string; quiet?: boolean }) => {
    if (videoId === null) {
      setPublishReadiness(null);
      return;
    }
    const baseUrl = options?.baseUrl ?? apiBaseUrlRef.current;
    const quiet = options?.quiet ?? false;
    try {
      const payload = await requestJson<PublishReadinessResponse>(baseUrl, `/internal/videos/${videoId}/publish-readiness`);
      setPublishReadiness(payload);
      if (!quiet) {
        setMessage({
          kind: "success",
          text: payload.ready ? "Checklist de publicacao completo." : "Checklist de publicacao atualizado com itens pendentes.",
        });
      }
    } catch (error) {
      setPublishReadiness(null);
      if (!quiet) {
        setMessage({
          kind: "error",
          text: error instanceof Error ? error.message : "Falha ao carregar checklist de publicacao.",
        });
      }
    }
  }, []);

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
      syncPerformanceForm(nextSelectedVideo);
      syncYoutubePrepForm(nextSelectedVideo);
      setSelectedVisualTemplate(nextSelectedVideo?.visual_template ?? DEFAULT_VISUAL_TEMPLATE);
      setPendingAssetId(null);
      setLatestJob(null);
      void loadContentBrainSignals({ quiet: true });
      void loadLatestJob(nextSelectedId, { quiet: true });
      void loadPublishReadiness(nextSelectedId, { quiet: true });
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
  }, [loadContentBrainSignals, loadLatestJob, loadPublishReadiness, syncPerformanceForm, syncYoutubePrepForm]);

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
    syncPerformanceForm(nextVideo);
    syncYoutubePrepForm(nextVideo);
    setSelectedVisualTemplate(nextVideo.visual_template ?? DEFAULT_VISUAL_TEMPLATE);
    setPendingAssetId(null);
    setLatestJob(null);
    void loadLatestJob(nextVideo.video_id, { quiet: true });
    void loadPublishReadiness(nextVideo.video_id, { quiet: true });
  }

  function selectVideo(video: VideoItem) {
    setSelectedVideoId(video.video_id);
    selectedVideoIdRef.current = video.video_id;
    setScriptDraft(buildScriptDraft(video));
    syncPerformanceForm(video);
    syncYoutubePrepForm(video);
    setSelectedVisualTemplate(video.visual_template ?? DEFAULT_VISUAL_TEMPLATE);
    setPendingAssetId(null);
    setLatestJob(null);
    void loadLatestJob(video.video_id, { quiet: true });
    void loadPublishReadiness(video.video_id, { quiet: true });
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
      void loadPublishReadiness(created.video_id, { quiet: true });
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
      void loadPublishReadiness(selectedVideoId, { quiet: true });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "Falha ao rodar o pipeline fake." });
    } finally {
      setBusyAction(null);
    }
  }

  async function enqueueBackgroundPipeline() {
    if (selectedVideoId === null) {
      setMessage({ kind: "error", text: "Selecione um video antes de enfileirar o pipeline." });
      return;
    }

    setBusyAction("enqueue-job");
    try {
      const job = await requestJson<VideoJobItem>(apiBaseUrl, `/internal/videos/${selectedVideoId}/jobs/produce`, {
        method: "POST",
        body: JSON.stringify({
          visual_template: selectedVisualTemplate,
        }),
      });
      setLatestJob(job);
      setMessage({ kind: "success", text: `Job ${job.job_id} enfileirado em background.` });
      void loadVideos({ quiet: true });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "Falha ao enfileirar o pipeline." });
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
      void loadPublishReadiness(updated.video_id, { quiet: true });
      setMessage({ kind: "success", text: `Status atualizado para o video ${selectedVideoId}.` });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "Falha ao consultar status." });
    } finally {
      setBusyAction(null);
    }
  }

  async function refreshLatestJob() {
    if (selectedVideoId === null) {
      setMessage({ kind: "error", text: "Selecione um video para consultar o job." });
      return;
    }

    setBusyAction("job-status");
    try {
      await loadLatestJob(selectedVideoId);
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "Falha ao consultar job." });
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
      void loadPublishReadiness(updated.video_id, { quiet: true });
      setMessage({ kind: "success", text: `Roteiro do video ${selectedVideoId} salvo com sucesso.` });
      void loadVideos({ quiet: true });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "Falha ao salvar roteiro." });
    } finally {
      setBusyAction(null);
    }
  }

  async function savePerformanceSignal() {
    if (selectedVideoId === null) {
      setMessage({ kind: "error", text: "Selecione um video antes de salvar o sinal." });
      return;
    }

    setBusyAction("save-performance");
    try {
      const updated = await requestJson<VideoItem>(apiBaseUrl, `/internal/videos/${selectedVideoId}/performance`, {
        method: "PATCH",
        body: JSON.stringify({
          performance_label: performanceLabel,
          notes: performanceNotes,
          reason_tags: parseReasonTagsInput(performanceReasonTagsText),
        }),
      });
      mergeVideo(updated);
      setPerformanceLabel(updated.performance_label ?? "unknown");
      setPerformanceNotes(updated.performance_notes ?? "");
      setPerformanceReasonTagsText(buildPerformanceReasonTagsText(updated));
      void loadPublishReadiness(updated.video_id, { quiet: true });
      setMessage({ kind: "success", text: `Sinal do video ${selectedVideoId} atualizado para ${updated.performance_label ?? "unknown"}.` });
      void loadVideos({ quiet: true });
      void loadContentBrainSignals({ quiet: true });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "Falha ao salvar o sinal do video." });
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
        void loadPublishReadiness(updated.video_id, { quiet: true });
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

  async function uploadLocalAsset() {
    if (!assetUploadFile) {
      setMessage({ kind: "error", text: "Escolha um arquivo antes de enviar o asset." });
      return;
    }
    if (!isAllowedUploadExtension(assetUploadFile.name)) {
      setMessage({ kind: "error", text: "Apenas .png, .jpg, .jpeg e .webp são permitidos. .mp4 continua bloqueado." });
      return;
    }

    setBusyAction("upload-asset");
    try {
      const searchParams = new URLSearchParams({
        filename: assetUploadFile.name,
        name: assetUploadName.trim() || assetUploadFile.name.replace(/\.[^.]+$/, ""),
        slug: assetUploadSlug.trim() || sanitizeUploadStem(assetUploadFile.name.replace(/\.[^.]+$/, "")),
        asset_type: "background_image",
        license_name: assetUploadLicenseName.trim() || DEFAULT_UPLOAD_FORM.licenseName,
      });
      if (assetUploadChannelSlug.trim()) {
        searchParams.set("channel_slug", assetUploadChannelSlug.trim());
      }
      if (assetUploadTopic.trim()) {
        searchParams.set("topic", assetUploadTopic.trim());
      }
      const tags = parseTagsInput(assetUploadTagsText);
      if (tags.length > 0) {
        searchParams.set("tags", tags.join(","));
      }

      const response = await fetch(
        `${normalizeBaseUrl(apiBaseUrl)}/internal/videos/assets/upload?${searchParams.toString()}`,
        {
          method: "POST",
          cache: "no-store",
          body: assetUploadFile,
        },
      );

      if (!response.ok) {
        const body = await response.text();
        throw new Error(body || `Request failed with status ${response.status}`);
      }

      const created = (await response.json()) as AssetItem;
      await loadAssets({ quiet: true });
      resetUploadForm();

      if (selectedVideoId !== null && canSelectAsset(selectedVideo)) {
        try {
          await applyAsset(created, { quiet: true });
          setMessage({ kind: "success", text: "Asset enviado e cadastrado. Asset aplicado ao vídeo atual." });
          return;
        } catch (error) {
          setMessage({
            kind: "error",
            text:
              error instanceof Error
                ? `Asset enviado e cadastrado, mas não foi possível aplicar ao vídeo atual: ${error.message}`
                : "Asset enviado e cadastrado, mas não foi possível aplicar ao vídeo atual.",
          });
          return;
        }
      }

      if (selectedVideoId !== null && canRegeneratePreview(selectedVideo)) {
        setPendingAssetId(created.asset_id);
        setMessage({
          kind: "success",
          text: "Asset enviado e cadastrado. Asset selecionado para regeneração do preview.",
        });
        return;
      }

      setMessage({ kind: "success", text: "Asset enviado e cadastrado." });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "Falha ao enviar asset local." });
    } finally {
      setBusyAction(null);
    }
  }

  function handleAssetUploadFileChange(file: File | null) {
    setAssetUploadFile(file);
    if (!file) {
      return;
    }
    const stem = file.name.replace(/\.[^.]+$/, "");
    if (!assetUploadName.trim()) {
      setAssetUploadName(stem.replace(/[-_]+/g, " ").trim() || stem);
    }
    if (!assetUploadSlug.trim()) {
      setAssetUploadSlug(sanitizeUploadStem(stem));
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
      void loadPublishReadiness(updated.video_id, { quiet: true });
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

  async function generateExportPackage() {
    if (selectedVideoId === null) {
      setMessage({ kind: "error", text: "Selecione um video antes de gerar o pacote de export." });
      return;
    }
    if (!exportPackageReady) {
      setMessage({ kind: "error", text: "O pacote de export so pode ser gerado depois do render final." });
      return;
    }

    setBusyAction("export-package");
    try {
      const updated = await requestJson<VideoItem>(apiBaseUrl, `/internal/videos/${selectedVideoId}/export-package`, {
        method: "POST",
      });
      mergeVideo(updated);
      void loadPublishReadiness(updated.video_id, { quiet: true });
      setMessage({ kind: "success", text: `Pacote de export gerado para o video ${selectedVideoId}.` });
      void loadVideos({ quiet: true });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "Falha ao gerar pacote de export." });
    } finally {
      setBusyAction(null);
    }
  }

  async function saveYouTubePrep() {
    if (selectedVideoId === null || selectedVideo === null) {
      setMessage({ kind: "error", text: "Selecione um video antes de salvar o YouTube Prep." });
      return;
    }
    if (!youtubePrepReady) {
      setMessage({ kind: "error", text: "YouTube Prep so pode ser salvo depois do render final." });
      return;
    }

    setBusyAction("youtube-prep");
    try {
      const updated = await requestJson<VideoItem>(apiBaseUrl, `/internal/videos/${selectedVideoId}/youtube-prep`, {
        method: "POST",
        body: JSON.stringify({
          title: youtubeTitle,
          description: youtubeDescription,
          tags: parseTagsInput(youtubeTagsText),
          visibility: youtubeVisibility,
          made_for_kids: false,
        }),
      });
      mergeVideo(updated);
      syncYoutubePrepForm(updated);
      void loadPublishReadiness(updated.video_id, { quiet: true });
      setMessage({ kind: "success", text: `YouTube Prep salvo para o video ${selectedVideoId}.` });
      void loadVideos({ quiet: true });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "Falha ao salvar o YouTube Prep." });
    } finally {
      setBusyAction(null);
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadVideos();
      void loadAssets({ quiet: true });
      void loadChannelPresets({ quiet: true });
      void loadContentBrainSignals({ quiet: true });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadVideos, loadAssets, loadChannelPresets, loadContentBrainSignals]);

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
          <button
            type="button"
            className="primary"
            onClick={() => void enqueueBackgroundPipeline()}
            disabled={busyAction !== null || selectedVideoId === null}
          >
            {busyAction === "enqueue-job" ? "Enfileirando..." : "Produzir em background"}
          </button>
          {pipelineCompleted ? <p className="helper">Este video ja esta finalizado. Atualize ou escolha outro item para rodar novamente.</p> : null}

          <div className={`message ${message.kind}`}>
            {message.text || "Pronto para operar o pipeline local."}
          </div>
        </aside>

        <section className="panel">
          <div className="panel-header">
            <h2>Videos recentes</h2>
            <div className="panel-actions">
              <span className="panel-hint">
                {filteredVideos.length} de {videos.length} itens
              </span>
              <select value={performanceFilter} onChange={(event) => setPerformanceFilter(event.target.value)}>
                <option value="all">Todos</option>
                <option value="winning">Winning</option>
                <option value="average">Average</option>
                <option value="weak">Weak</option>
                <option value="unknown">Unknown</option>
              </select>
            </div>
          </div>
          <div className="badge-row spaced">
            <span className="badge success">winning: {contentBrainWinningCount}</span>
            <span className="badge warning">weak: {contentBrainWeakCount}</span>
          </div>

          <div className="video-list">
            {filteredVideos.length === 0 ? (
              <div className="empty-state">
                Nenhum video encontrado. Crie um video fake para comecar.
              </div>
            ) : (
              filteredVideos.map((video) => {
                const isSelected = video.video_id === selectedVideoId;
                const performanceClass = video.performance_label ?? "unknown";
                return (
                  <button
                    key={video.video_id}
                    type="button"
                    className={`video-card performance-${performanceClass}${isSelected ? " selected" : ""}`}
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
                        <span className={`badge ${performanceClass === "winning" ? "success" : performanceClass === "weak" ? "warning" : "subtle"}`}>
                          {video.performance_label ?? "unknown"}
                        </span>
                        <span className={`badge ${video.content_brain_context_used ? "success" : "subtle"}`}>
                          CB {video.content_brain_context_used ? "on" : "off"}
                        </span>
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
                    {video.performance_notes ? <p className="helper">Sinal: {video.performance_notes}</p> : null}
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
              {selectedVideo.video_title ? (
                <p>
                  <strong>Titulo sugerido:</strong> {selectedVideo.video_title}
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
              <div className="detail-asset">
                <div className="panel-header">
                  <h3>ContentBrain aplicado</h3>
                  <span className="panel-hint">
                    {selectedVideo.content_brain_context_used ? "sinais usados no roteiro" : "nenhum sinal aplicado"}
                  </span>
                </div>
                <p>
                  <strong>Usado:</strong> {selectedVideo.content_brain_context_used ? "sim" : "nao"}
                </p>
                <p>
                  <strong>Winning:</strong> {selectedVideo.winning_signals_count ?? 0}
                </p>
                <p>
                  <strong>Weak:</strong> {selectedVideo.weak_signals_count ?? 0}
                </p>
                {selectedVideo.applied_reason_tags?.length ? (
                  <div>
                    <strong>Tags aplicadas:</strong>
                    <AssetTags tags={selectedVideo.applied_reason_tags} />
                  </div>
                ) : null}
              </div>
              <div className="detail-asset">
                <div className="panel-header">
                  <h3>ContentBrain local</h3>
                  <span className="panel-hint">label atual: {selectedVideoPerformanceLabel}</span>
                </div>
                <label className="field">
                  <span>Performance label</span>
                  <select value={performanceLabel} onChange={(event) => setPerformanceLabel(event.target.value)}>
                    <option value="unknown">unknown</option>
                    <option value="weak">weak</option>
                    <option value="average">average</option>
                    <option value="winning">winning</option>
                  </select>
                </label>
                <label className="field">
                  <span>Notes</span>
                  <textarea
                    value={performanceNotes}
                    onChange={(event) => setPerformanceNotes(event.target.value)}
                    rows={4}
                    placeholder="Notas manuais sobre o que funcionou ou nao funcionou."
                  />
                </label>
                <label className="field">
                  <span>Reason tags</span>
                  <input
                    value={performanceReasonTagsText}
                    onChange={(event) => setPerformanceReasonTagsText(event.target.value)}
                    placeholder="hook, ritmo, CTA"
                  />
                </label>
                <div className="panel-actions">
                  <span className="panel-hint">Sinais sao locais e ajudam o Script Engine com contexto opcional.</span>
                  <button
                    type="button"
                    className="primary secondary"
                    onClick={() => void savePerformanceSignal()}
                    disabled={busyAction !== null}
                  >
                    {busyAction === "save-performance" ? "Salvando..." : "Salvar sinal"}
                  </button>
                </div>
              </div>
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
              <div className={`job-card${latestJob?.status === "failed" ? " failed" : ""}`}>
                <div className="panel-header">
                  <h3>Job em background</h3>
                  <div className="panel-actions">
                    <span className="panel-hint">{latestJob ? latestJob.job_id : "nenhum job"}</span>
                    <button type="button" className="ghost" onClick={() => void refreshLatestJob()} disabled={busyAction !== null}>
                      Atualizar job
                    </button>
                  </div>
                </div>
                {latestJob ? (
                  <div className="detail-asset">
                    <p>
                      <strong>Tipo:</strong> {latestJob.job_type}
                    </p>
                    <p>
                      <strong>Status:</strong> {latestJob.status}
                    </p>
                    <p>
                      <strong>Criado em:</strong> {formatJobTimestamp(latestJob.created_at)}
                    </p>
                    <p>
                      <strong>Iniciado em:</strong> {formatJobTimestamp(latestJob.started_at)}
                    </p>
                    <p>
                      <strong>Finalizado em:</strong> {formatJobTimestamp(latestJob.finished_at)}
                    </p>
                    {latestJob.visual_template ? (
                      <p>
                        <strong>Template:</strong> {latestJob.visual_template}
                      </p>
                    ) : null}
                    {latestJob.error_message ? (
                      <p className="warning">
                        <strong>Erro:</strong> {latestJob.error_message}
                      </p>
                    ) : null}
                  </div>
                ) : (
                  <p className="helper">Nenhum job enfileirado para este video ainda.</p>
                )}
              </div>
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
                <button
                  type="button"
                  onClick={() => void generateExportPackage()}
                  disabled={busyAction !== null || !exportPackageReady}
                >
                  {busyAction === "export-package" ? "Gerando export..." : "Gerar pacote de export"}
                </button>
              </div>
              <p className="helper">
                Cada botao segue a ordem real do pipeline. Se o stage atual nao permitir a etapa, a API responde com erro claro.
              </p>
              {exportPackageReady ? (
                <p className="helper">Depois do render final, voce pode gerar o pacote local com metadata e arquivos exportados.</p>
              ) : null}
            </div>

            <div className="asset-form">
              <div className="panel-header">
                <h3>YouTube Prep</h3>
                <span className="panel-hint">{youtubePrepReady ? "pronto para salvar" : "aguardando final render"}</span>
              </div>
              <div className="asset-form-grid">
                <label className="field asset-form-tags">
                  <span>Title</span>
                  <input value={youtubeTitle} onChange={(event) => setYoutubeTitle(event.target.value)} disabled={!youtubePrepReady || busyAction !== null} />
                </label>
                <label className="field">
                  <span>Visibility</span>
                  <select value={youtubeVisibility} onChange={(event) => setYoutubeVisibility(event.target.value)} disabled={!youtubePrepReady || busyAction !== null}>
                    <option value="private">private</option>
                    <option value="unlisted">unlisted</option>
                    <option value="public">public</option>
                  </select>
                </label>
                <label className="field asset-form-tags">
                  <span>Description</span>
                  <textarea
                    value={youtubeDescription}
                    onChange={(event) => setYoutubeDescription(event.target.value)}
                    disabled={!youtubePrepReady || busyAction !== null}
                    rows={8}
                  />
                </label>
                <label className="field asset-form-tags">
                  <span>Tags</span>
                  <input value={youtubeTagsText} onChange={(event) => setYoutubeTagsText(event.target.value)} disabled={!youtubePrepReady || busyAction !== null} />
                </label>
              </div>
              <div className="asset-form-actions">
                <span className="panel-hint">made_for_kids: false por padrao</span>
                <button type="button" className="primary secondary" onClick={() => void saveYouTubePrep()} disabled={!youtubePrepReady || busyAction !== null}>
                  {busyAction === "youtube-prep" ? "Salvando..." : "Salvar YouTube Prep"}
                </button>
              </div>
              {selectedVideo.youtube_publish_path ? (
                <p className="helper">
                  JSON salvo em <code>{selectedVideo.youtube_publish_path}</code>.
                </p>
              ) : (
                <p className="helper">Salve o JSON local depois do render final para preparar a publicacao manualmente.</p>
              )}
            </div>

            <div className="asset-form">
              <div className="panel-header">
                <h3>Pronto para publicar?</h3>
                <div className="badges">
                  <span className={`badge ${publishReady ? "success" : "warning"}`}>
                    {publishReady ? "ready" : "missing_items"}
                  </span>
                  <span className="panel-hint">{publishReadiness?.stage_status ?? "aguardando final render"}</span>
                </div>
              </div>
              {selectedVideo?.stage_status !== "final_rendered" ? (
                <p className="helper">O checklist so fica disponivel depois do render final e do pacote de export.</p>
              ) : null}
              {publishReadiness ? (
                <div className="detail-asset">
                  <p>
                    <strong>Status geral:</strong> {publishReadiness.overall_status}
                  </p>
                  <p>
                    <strong>Itens faltando:</strong>{" "}
                    {publishReadiness.missing_items.length ? publishReadiness.missing_items.join(", ") : "nenhum"}
                  </p>
                  <div className="badge-row">
                    {publishReadiness.items.map((item) => (
                      <span key={item.key} className={`badge ${item.ready ? "success" : "warning"}`}>
                        {item.ready ? "OK" : "pendente"}: {item.label}
                      </span>
                    ))}
                  </div>
                  <div className="paths">
                    {publishReadiness.items.map((item) => (
                      <div key={item.key} className="path-row">
                        <span className="path-label">{item.label}</span>
                        <code className={`path-value${item.ready ? "" : " is-empty"}`}>
                          {item.value ?? (item.ready ? "ok" : "pendente")}
                        </code>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <p className="helper">Abra um video finalizado para ver o checklist de publicacao.</p>
              )}
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
              <div className="asset-upload-form">
                <div className="panel-header">
                  <h3>Upload local</h3>
                  <span className="panel-hint">png / jpg / jpeg / webp</span>
                </div>
                <div className="asset-form-grid">
                  <label className="field asset-form-tags">
                    <span>Arquivo</span>
                    <input
                      type="file"
                      accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp"
                      onChange={(event) => handleAssetUploadFileChange(event.target.files?.[0] ?? null)}
                    />
                  </label>
                  <label className="field">
                    <span>Nome</span>
                    <input value={assetUploadName} onChange={(event) => setAssetUploadName(event.target.value)} />
                  </label>
                  <label className="field">
                    <span>Slug</span>
                    <input value={assetUploadSlug} onChange={(event) => setAssetUploadSlug(event.target.value)} />
                  </label>
                  <label className="field">
                    <span>Licença</span>
                    <input value={assetUploadLicenseName} onChange={(event) => setAssetUploadLicenseName(event.target.value)} />
                  </label>
                  <label className="field">
                    <span>Channel slug opcional</span>
                    <input
                      value={assetUploadChannelSlug}
                      onChange={(event) => setAssetUploadChannelSlug(event.target.value)}
                    />
                  </label>
                  <label className="field">
                    <span>Tema/nicho opcional</span>
                    <input value={assetUploadTopic} onChange={(event) => setAssetUploadTopic(event.target.value)} />
                  </label>
                  <label className="field asset-form-tags">
                    <span>Tags opcional</span>
                    <input value={assetUploadTagsText} onChange={(event) => setAssetUploadTagsText(event.target.value)} />
                  </label>
                </div>
                <div className="asset-form-actions">
                  <span className="panel-hint">
                    Destino seguro: <code>storage/assets/uploads</code>. .mp4 continua bloqueado.
                  </span>
                  <button type="button" className="primary secondary" onClick={() => void uploadLocalAsset()} disabled={busyAction !== null}>
                    {busyAction === "upload-asset" ? "Enviando..." : "Enviar arquivo"}
                  </button>
                </div>
                {assetUploadFile ? <p className="helper">Arquivo selecionado: {assetUploadFile.name}</p> : null}
              </div>
              <div className="asset-form">
                <div className="panel-header">
                  <h3>Cadastro local por caminho</h3>
                  <span className="panel-hint">reaproveita um arquivo já existente em storage/assets</span>
                </div>
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
              <PathLine label="export_metadata_path" value={selectedVideo.export_metadata_path} />
              <PathLine label="export_final_path" value={selectedVideo.export_final_path} />
              <PathLine label="export_caption_path" value={selectedVideo.export_caption_path} />
              <PathLine label="export_preview_path" value={selectedVideo.export_preview_path} />
              <PathLine label="youtube_publish_path" value={selectedVideo.youtube_publish_path} />
            </div>
          </div>
        ) : (
          <div className="empty-state">Selecione um video na lista para ver os paths gerados.</div>
        )}
      </section>
    </main>
  );
}
