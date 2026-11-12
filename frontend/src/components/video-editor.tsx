"use client";

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import Image from "next/image";
import {
  AudioLines,
  Check,
  ChevronDown,
  ChevronUp,
  Clapperboard,
  Copy,
  Download,
  FileAudio2,
  FileImage,
  FileVideo2,
  Lock,
  LockKeyholeOpen,
  Pause,
  Play,
  Plus,
  Redo2,
  Scissors,
  Trash2,
  Undo2,
  Upload,
  Volume2,
  VolumeX,
} from "lucide-react";
import { Badge, Button, Card, Dialog, Field, SelectInput, TextInput } from "@/components/ui";
import {
  TimelineCompositePreview,
  type TimelinePreviewHandle,
} from "@/components/timeline-composite-preview";
import {
  authenticate,
  cancelMediaJob,
  downloadMedia,
  getMediaJob,
  loadMediaDerivative,
  retryMediaJob,
  uploadMedia,
  type MediaJob,
} from "@/lib/media-api";
import {
  createStudioProject,
  BACKEND_URL_KEY,
  cancelTimelineExport,
  DEFAULT_BACKEND_URL,
  DEFAULT_TIMELINE_TEXT_STYLE,
  downloadSubtitles,
  downloadTimelineExport,
  importSubtitleFile,
  getTimelineExport,
  listStudioMedia,
  listStudioProjects,
  loadTimeline,
  MEDIA_TOKEN_KEY,
  queueTimelineExport,
  proposeTimelineTextFit,
  retryTimelineExport,
  saveTimeline,
  validateTimelineText,
  type StudioProject,
  type TimelineClip,
  type TimelineDocument,
  type TimelineEffect,
  type TimelineEffectType,
  type TimelineTrack,
  type TimelineTrackType,
  type TimelineTextStyle,
  type TimelineTextFitOperation,
  type TimelineTextValidationIssue,
  type SubtitleCue,
} from "@/lib/timeline-api";
import type { MediaAsset } from "@/lib/media-api";

type PanelName = "Media" | "Audio" | "Text" | "Effects" | "Transitions" | "Assets";
type SaveState = "saved" | "saving" | "unsaved" | "error";
type TitlePreset = "basic" | "centered" | "opening" | "ending" | "lower-third" | "section" | "callout";
type DragState = {
  trackId: string;
  clipId: string;
  pointerX: number;
  initialStart: number;
  currentTrackId: string;
  initialTimeline: TimelineDocument;
  changed: boolean;
};
type TextFitProposal = {
  timeline: TimelineDocument;
  source: TimelineDocument;
  warnings: string[];
};

const panelNames: PanelName[] = ["Media", "Audio", "Text", "Effects", "Transitions", "Assets"];
const panelIcons = [FileVideo2, FileAudio2, Clapperboard, Clapperboard, Clapperboard, FileImage];
const freshId = () => crypto.randomUUID();
const titlePresets: Record<TitlePreset, {
  label: string;
  position_x: number;
  position_y: number;
  fade_in: number;
  fade_out: number;
  style: Partial<TimelineTextStyle>;
}> = {
  basic: { label: "Basic title", position_x: 0.5, position_y: 0.2, fade_in: 0, fade_out: 0, style: {} },
  centered: { label: "Centered title", position_x: 0.5, position_y: 0.5, fade_in: 0, fade_out: 0, style: { font_size: 64 } },
  opening: { label: "Opening title", position_x: 0.5, position_y: 0.42, fade_in: 0.6, fade_out: 0, style: { font_size: 72, background_opacity: 0.25 } },
  ending: { label: "Ending title", position_x: 0.5, position_y: 0.72, fade_in: 0, fade_out: 0.6, style: { font_size: 56 } },
  "lower-third": { label: "Lower third", position_x: 0.08, position_y: 0.72, fade_in: 0.25, fade_out: 0.25, style: { font_size: 42, alignment: "left", vertical_alignment: "middle", background_opacity: 0.82, width: 0.72 } },
  section: { label: "Section heading", position_x: 0.5, position_y: 0.14, fade_in: 0.2, fade_out: 0.2, style: { font_size: 48, background_opacity: 0.35, width: 0.7 } },
  callout: { label: "Callout text", position_x: 0.72, position_y: 0.3, fade_in: 0.15, fade_out: 0.15, style: { font_size: 38, alignment: "right", background_opacity: 0.8, width: 0.45 } },
};
const effectLimits: Record<TimelineEffectType, { label: string; min: number; max: number; step: number; initial: number }> = {
  brightness: { label: "Brightness", min: -1, max: 1, step: 0.05, initial: 0.1 },
  contrast: { label: "Contrast", min: 0, max: 3, step: 0.05, initial: 1.1 },
  saturation: { label: "Saturation", min: 0, max: 3, step: 0.05, initial: 1.1 },
  grayscale: { label: "Grayscale", min: 0, max: 1, step: 0.05, initial: 1 },
  blur: { label: "Blur", min: 0, max: 20, step: 0.5, initial: 4 },
};

function subscribeToToken(onChange: () => void) {
  window.addEventListener("storage", onChange);
  window.addEventListener("ai-creator-studio:token-change", onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener("ai-creator-studio:token-change", onChange);
  };
}

function readStoredToken() {
  return typeof window === "undefined" ? "" : window.sessionStorage.getItem(MEDIA_TOKEN_KEY) ?? "";
}

function readStoredBackendUrl() {
  return typeof window === "undefined"
    ? DEFAULT_BACKEND_URL
    : window.localStorage.getItem(BACKEND_URL_KEY) ?? DEFAULT_BACKEND_URL;
}

function subscribeToBackendUrl(onChange: () => void) {
  window.addEventListener("storage", onChange);
  window.addEventListener("ai-creator-studio:backend-url-change", onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener("ai-creator-studio:backend-url-change", onChange);
  };
}

function writeStoredBackendUrl(url: string) {
  window.localStorage.setItem(BACKEND_URL_KEY, url);
  window.dispatchEvent(new Event("ai-creator-studio:backend-url-change"));
}

function writeStoredToken(token: string | null) {
  if (token) window.sessionStorage.setItem(MEDIA_TOKEN_KEY, token);
  else window.sessionStorage.removeItem(MEDIA_TOKEN_KEY);
  window.dispatchEvent(new Event("ai-creator-studio:token-change"));
}

function formatTime(seconds: number) {
  const safe = Math.max(0, seconds);
  const minutes = Math.floor(safe / 60).toString().padStart(2, "0");
  const wholeSeconds = Math.floor(safe % 60).toString().padStart(2, "0");
  const frames = Math.floor((safe % 1) * 24).toString().padStart(2, "0");
  return `${minutes}:${wholeSeconds}:${frames}`;
}

function freshTimeline(): TimelineDocument {
  return {
    version: 1,
    name: "Main timeline",
    frame_rate: 24,
    width: 1920,
    height: 1080,
    tracks: [
      { id: "00000000-0000-4000-8000-000000000001", name: "V1", type: "video", muted: false, locked: false, volume: 1, clips: [] },
      { id: "00000000-0000-4000-8000-000000000002", name: "O1", type: "overlay", muted: false, locked: false, volume: 1, clips: [] },
      { id: "00000000-0000-4000-8000-000000000003", name: "A1", type: "audio", muted: false, locked: false, volume: 1, clips: [] },
      { id: "00000000-0000-4000-8000-000000000004", name: "T1", type: "subtitle", muted: false, locked: false, volume: 1, clips: [] },
    ],
  };
}

function responseMessage(error: unknown) {
  return error instanceof Error ? error.message : "The request could not be completed.";
}

function AssetThumbnail({
  asset,
  baseUrl,
  token,
}: {
  asset: MediaAsset;
  baseUrl: string;
  token: string;
}) {
  const [loadedThumbnail, setLoadedThumbnail] = useState<{ assetId: string; url: string } | null>(null);
  const [failedAssetId, setFailedAssetId] = useState("");

  useEffect(() => {
    if (!token || !asset.metadata_json?.derivatives?.thumbnail) return;
    let active = true;
    let objectUrl = "";
    void loadMediaDerivative(baseUrl, token, asset.id, "thumbnail").then((url) => {
      objectUrl = url;
      if (active) setLoadedThumbnail({ assetId: asset.id, url });
      else URL.revokeObjectURL(url);
    }).catch(() => {
      if (active) setFailedAssetId(asset.id);
    });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [asset.id, asset.metadata_json, baseUrl, token]);

  const thumbnail = loadedThumbnail?.assetId === asset.id ? loadedThumbnail.url : "";
  return thumbnail
    ? <Image alt="" className="editor-asset-thumbnail" height={42} src={thumbnail} unoptimized width={64} />
    : <span aria-label={failedAssetId === asset.id ? "Thumbnail unavailable" : "Thumbnail pending"} className="editor-asset-thumbnail-placeholder" />;
}

function AudioWaveform({
  asset,
  baseUrl,
  token,
}: {
  asset: MediaAsset | undefined;
  baseUrl: string;
  token: string;
}) {
  const [waveformUrl, setWaveformUrl] = useState("");

  useEffect(() => {
    if (!asset || !token || !asset.metadata_json?.derivatives?.waveform) return;
    let active = true;
    let objectUrl = "";
    void loadMediaDerivative(baseUrl, token, asset.id, "waveform").then((url) => {
      objectUrl = url;
      if (active) setWaveformUrl(url);
      else URL.revokeObjectURL(url);
    }).catch(() => {
      if (active) setWaveformUrl("");
    });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [asset, baseUrl, token]);

  return waveformUrl
    ? <Image alt="Audio waveform" className="editor-timeline-waveform" height={24} src={waveformUrl} unoptimized width={120} />
    : null;
}

export function VideoEditor() {
  const baseUrl = useSyncExternalStore(subscribeToBackendUrl, readStoredBackendUrl, () => DEFAULT_BACKEND_URL);
  const token = useSyncExternalStore(subscribeToToken, readStoredToken, () => "");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [createAccount, setCreateAccount] = useState(false);
  const [projectDialogOpen, setProjectDialogOpen] = useState(false);
  const [projectName, setProjectName] = useState("");
  const [subtitleDialogOpen, setSubtitleDialogOpen] = useState(false);
  const [subtitleText, setSubtitleText] = useState("");
  const [titlePreset, setTitlePreset] = useState<TitlePreset>("basic");
  const [subtitleImporting, setSubtitleImporting] = useState(false);
  const [textValidationIssues, setTextValidationIssues] = useState<TimelineTextValidationIssue[]>([]);
  const [textValidationError, setTextValidationError] = useState("");
  const [textValidationLoading, setTextValidationLoading] = useState(false);
  const [textFitProposal, setTextFitProposal] = useState<TextFitProposal | null>(null);
  const [textFitError, setTextFitError] = useState("");
  const [textFitLoading, setTextFitLoading] = useState(false);
  const [minimumTextFontSize, setMinimumTextFontSize] = useState(18);
  const [projects, setProjects] = useState<StudioProject[]>([]);
  const [projectId, setProjectId] = useState("");
  const [assets, setAssets] = useState<MediaAsset[]>([]);
  const [timeline, setTimeline] = useState<TimelineDocument>(freshTimeline);
  const [loadedProjectId, setLoadedProjectId] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [error, setError] = useState("");
  const [activePanel, setActivePanel] = useState<PanelName>("Media");
  const [selectedClip, setSelectedClip] = useState("");
  const [playhead, setPlayhead] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [zoom, setZoom] = useState(56);
  const [keyframeProperty, setKeyframeProperty] = useState<"x" | "y" | "scale" | "opacity" | "volume">("opacity");
  const [keyframeValue, setKeyframeValue] = useState(1);
  const [newEffectType, setNewEffectType] = useState<TimelineEffectType>("brightness");
  const [exportMessage, setExportMessage] = useState("");
  const [exportJobId, setExportJobId] = useState("");
  const [exportJobStatus, setExportJobStatus] = useState<MediaJob["status"] | "">("");
  const [exportProgress, setExportProgress] = useState(0);
  const [exportPreset, setExportPreset] = useState<"720p" | "1080p" | "4k">("1080p");
  const [exportRetryCount, setExportRetryCount] = useState(0);
  const [exportMaxRetries, setExportMaxRetries] = useState(2);
  const [exporting, setExporting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [mediaJobs, setMediaJobs] = useState<Record<string, MediaJob>>({});
  const [seekRevision, setSeekRevision] = useState(0);
  const [undoStack, setUndoStack] = useState<TimelineDocument[]>([]);
  const [redoStack, setRedoStack] = useState<TimelineDocument[]>([]);
  const dragState = useRef<DragState | null>(null);
  const previewRef = useRef<TimelinePreviewHandle>(null);
  const playheadRef = useRef(0);
  const timelineRef = useRef(timeline);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const subtitleFileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    timelineRef.current = timeline;
  }, [timeline]);

  const refreshLibrary = useCallback(async (authToken: string) => {
    const [nextProjects, nextAssets] = await Promise.all([
      listStudioProjects(baseUrl, authToken),
      listStudioMedia(baseUrl, authToken),
    ]);
    setProjects(nextProjects);
    setAssets(nextAssets);
    setProjectId((current) => current && nextProjects.some((project) => project.id === current)
      ? current
      : nextProjects[0]?.id ?? "");
  }, [baseUrl]);

  useEffect(() => {
    if (!token) return;
    let active = true;
    void Promise.all([listStudioProjects(baseUrl, token), listStudioMedia(baseUrl, token)])
      .then(([nextProjects, nextAssets]) => {
        if (!active) return;
        setProjects(nextProjects);
        setAssets(nextAssets);
        setProjectId((current) => current && nextProjects.some((project) => project.id === current)
          ? current
          : nextProjects[0]?.id ?? "");
      })
      .catch((loadError: unknown) => {
        if (active) setError(responseMessage(loadError));
      });
    return () => { active = false; };
  }, [baseUrl, token]);

  useEffect(() => {
      if (!token) return;
      const pendingAssets = assets.filter((asset) => {
        const jobId = asset.metadata_json?.processing_job_id;
        const job = mediaJobs[asset.id];
        return Boolean(jobId && !asset.metadata_json?.probe &&
          (!job || job.status === "queued" || job.status === "processing"));
      });
      if (!pendingAssets.length) return;
      let active = true;
      const poll = async () => {
        const results = await Promise.all(pendingAssets.map(async (asset) => {
          const jobId = asset.metadata_json?.processing_job_id;
          if (!jobId) return null;
          try {
            return { assetId: asset.id, job: await getMediaJob(baseUrl, token, jobId) };
          } catch (jobError) {
            if (active) setError(responseMessage(jobError));
            return null;
          }
        }));
        if (!active) return;
        const completed = results.flatMap((result) =>
          result?.job.status === "completed" &&
          mediaJobs[result.assetId]?.status !== "completed" ? [result] : []);
        setMediaJobs((current) => {
          let changed = false;
          const next = { ...current };
          for (const result of results) {
            if (!result) continue;
            const previous = current[result.assetId];
            if (!previous || previous.status !== result.job.status ||
                previous.progress !== result.job.progress ||
                previous.error_message !== result.job.error_message) {
              next[result.assetId] = result.job;
              changed = true;
            }
          }
          return changed ? next : current;
        });
        if (completed.length) {
          try {
            setAssets(await listStudioMedia(baseUrl, token));
          } catch (refreshError) {
            setError(responseMessage(refreshError));
          }
        }
      };
      void poll();
      const timer = window.setInterval(() => void poll(), 1200);
      return () => {
        active = false;
        window.clearInterval(timer);
      };
  }, [assets, baseUrl, mediaJobs, token]);

  useEffect(() => {
    if (!token || !projectId) return;
    let active = true;
    void loadTimeline(baseUrl, token, projectId).then((result) => {
      if (!active) return;
      setTimeline(result.timeline_data);
      playheadRef.current = 0;
      setPlayhead(0);
      setSeekRevision((revision) => revision + 1);
      setPlaying(false);
      setDirty(false);
      setSaveState("saved");
      setUndoStack([]);
      setRedoStack([]);
      setSelectedClip("");
      setLoadedProjectId(result.project_id);
    }).catch((loadError: unknown) => {
      if (active) {
        setError(responseMessage(loadError));
        setSaveState("error");
      }
    });
    return () => { active = false; };
  }, [baseUrl, projectId, token]);

  useEffect(() => {
    if (!token || !projectId || loadedProjectId !== projectId || !dirty) return;
    const snapshot = timeline;
    const timer = window.setTimeout(() => {
      setSaveState("saving");
      void saveTimeline(baseUrl, token, projectId, snapshot).then(() => {
        if (timelineRef.current === snapshot) {
          setDirty(false);
          setSaveState("saved");
        }
      }).catch((saveError: unknown) => {
        setError(responseMessage(saveError));
        setSaveState("error");
      });
    }, 750);
    return () => window.clearTimeout(timer);
  }, [baseUrl, dirty, loadedProjectId, projectId, timeline, token]);

  useEffect(() => {
    if (!token || !projectId || loadedProjectId !== projectId) return;
    let active = true;
    if (!timeline.tracks.some((track) => !track.muted
      && (track.type === "overlay" || track.type === "subtitle")
      && track.clips.some((clip) => clip.text !== null && clip.text !== undefined))) {
      return;
    }
    const timer = window.setTimeout(() => {
      setTextValidationLoading(true);
      void validateTimelineText(baseUrl, token, projectId, timeline, exportPreset)
        .then((result) => {
          if (!active) return;
          setTextValidationIssues(result.issues);
          setTextValidationError("");
        })
        .catch((validationError: unknown) => {
          if (!active) return;
          setTextValidationError(responseMessage(validationError));
        })
        .finally(() => {
          if (active) setTextValidationLoading(false);
        });
    }, 650);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [baseUrl, exportPreset, loadedProjectId, projectId, timeline, token]);

  const assetById = useMemo(() => new Map(assets.map((asset) => [asset.id, asset])), [assets]);
  const allVideoClips = useMemo(() => timeline.tracks
    .filter((track) => (track.type === "video" || track.type === "overlay") && !track.muted)
    .flatMap((track) => track.clips
      .filter((clip) => assetById.get(clip.media_asset_id ?? "")?.media_type === "video")
      .map((clip) => ({ track, clip })))
    .sort((left, right) => left.clip.start - right.clip.start), [assetById, timeline.tracks]);
  const allAudioClips = useMemo(() => timeline.tracks
    .filter((track) => track.type === "audio" && !track.muted)
    .flatMap((track) => track.clips.map((clip) => ({ track, clip })))
    .sort((left, right) => left.clip.start - right.clip.start), [timeline.tracks]);
  const activeVisual = [...timeline.tracks].reverse()
    .filter((track) => (track.type === "video" || track.type === "overlay") && !track.muted)
    .flatMap((track) => track.clips.map((clip) => ({ track, clip })))
    .find(({ clip }) => playhead >= clip.start && playhead < clip.start + clip.duration
      && ["video", "image"].includes(assetById.get(clip.media_asset_id ?? "")?.media_type ?? ""));
  const activePreviewAsset = activeVisual?.clip.media_asset_id
    ? assetById.get(activeVisual.clip.media_asset_id)
    : undefined;
  const selected = timeline.tracks.flatMap((track) => track.clips.map((clip) => ({ track, clip })))
    .find(({ clip }) => clip.id === selectedClip);
  const subtitleEntries = timeline.tracks
    .filter((track) => track.type === "subtitle")
    .flatMap((track) => track.clips.map((clip) => ({ track, clip })))
    .filter(({ clip }) => Boolean(clip.text))
    .sort((left, right) => left.clip.start - right.clip.start);
  const selectedSubtitleNext = selected?.track.type === "subtitle"
    ? [...selected.track.clips]
      .filter((clip) => clip.id !== selectedClip
        && clip.start >= selected.clip.start + selected.clip.duration - 0.02)
      .sort((left, right) => left.start - right.start)[0]
    : undefined;
  const selectedTextClip = Boolean(
    selected && selected.clip.text !== null && selected.clip.text !== undefined
      && (selected.track.type === "overlay" || selected.track.type === "subtitle"),
  );
  const selectedTextIssues = textValidationIssues.filter((issue) => issue.clip_id === selectedClip);
  const projectHasText = timeline.tracks.some((track) => !track.muted
    && (track.type === "overlay" || track.type === "subtitle")
    && track.clips.some((clip) => clip.text !== null && clip.text !== undefined));
  const blockingTextIssueCount = textValidationIssues.filter((issue) => issue.severity === "error").length;
  const warningTextIssueCount = textValidationIssues.filter((issue) => issue.severity === "warning").length;
  const selectedTextStyle = { ...DEFAULT_TIMELINE_TEXT_STYLE, ...selected?.clip.text_style };
  const selectedTrackLocked = Boolean(selected?.track.locked);
  const selectedPreviousClip = selected
    ? [...selected.track.clips]
      .filter((clip) => clip.id !== selectedClip && clip.start < selected.clip.start)
      .sort((left, right) => left.start - right.start)
      .at(-1)
    : undefined;
  const selectedCrossDissolveOverlap = Math.max(
    0,
    selected && selectedPreviousClip
      ? selectedPreviousClip.start + selectedPreviousClip.duration - selected.clip.start
      : 0,
  );
  const timelineDuration = Math.max(0, ...timeline.tracks.flatMap((track) =>
    track.clips.map((clip) => clip.start + clip.duration)));
  const rulerDuration = Math.max(30, timelineDuration);
  const hasPreviewAudio = timeline.tracks.some((track) =>
    !track.muted && ["audio", "video", "overlay"].includes(track.type)
    && track.clips.some((clip) => assetById.get(clip.media_asset_id ?? "")?.metadata_json?.probe?.audio_streams?.length));
  const selectedMedia = selected?.clip.media_asset_id
    ? assetById.get(selected.clip.media_asset_id)
    : undefined;

  const seekTo = useCallback((time: number) => {
    const snappedTime = Math.max(0, Math.min(
      timelineDuration,
      Math.round(time * timeline.frame_rate) / timeline.frame_rate,
    ));
    playheadRef.current = snappedTime;
    setPlayhead(snappedTime);
    setSeekRevision((revision) => revision + 1);
  }, [timeline.frame_rate, timelineDuration]);

  const navigateToTextIssue = (clipId: string) => {
    const clip = timeline.tracks.flatMap((track) => track.clips).find((item) => item.id === clipId);
    if (!clip) return;
    setActivePanel("Text");
    setSelectedClip(clipId);
    seekTo(clip.start);
  };

  const startPlayback = useCallback(() => {
    const active = timeline.tracks.some((track) => !track.muted
      && (track.type === "video" || track.type === "overlay" || track.type === "audio")
      && track.clips.some((clip) => playheadRef.current >= clip.start
        && playheadRef.current < clip.start + clip.duration));
    const next = [...allVideoClips, ...allAudioClips]
      .filter(({ clip }) => clip.start >= playheadRef.current)
      .sort((left, right) => left.clip.start - right.clip.start)[0];
    if (!active && !next) return;
    if (!active && next) seekTo(next.clip.start);
    if (hasPreviewAudio && previewRef.current) {
      void previewRef.current.resumeAudio().then(
        () => setPlaying(true),
        (audioError: unknown) => {
          setError(responseMessage(audioError));
          setPlaying(true);
        },
      );
    } else {
      setPlaying(true);
    }
  }, [allAudioClips, allVideoClips, hasPreviewAudio, seekTo, timeline.tracks]);

  const togglePlayback = useCallback(() => {
    if (playing) setPlaying(false);
    else startPlayback();
  }, [playing, startPlayback]);

  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    let lastTimestamp = performance.now();
    const tick = (timestamp: number) => {
      const elapsed = Math.max(0, (timestamp - lastTimestamp) / 1000);
      lastTimestamp = timestamp;
      const next = Math.min(timelineDuration, playheadRef.current + elapsed);
      playheadRef.current = next;
      setPlayhead(next);
      if (next >= timelineDuration) {
        setPlaying(false);
        return;
      }
      frame = window.requestAnimationFrame(tick);
    };
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [playing, timelineDuration]);

  useEffect(() => {
    const onVisibilityChange = () => {
      if (document.visibilityState === "hidden") setPlaying(false);
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => document.removeEventListener("visibilitychange", onVisibilityChange);
  }, []);

  const editTimeline = useCallback((update: (current: TimelineDocument) => TimelineDocument) => {
    setTimeline((current) => {
      const next = update(current);
      if (next === current) return current;
      setUndoStack((history) => [...history.slice(-39), structuredClone(current)]);
      setRedoStack([]);
      setDirty(true);
      setSaveState("unsaved");
      return next;
    });
  }, []);

  const undo = useCallback(() => {
    const previous = undoStack.at(-1);
    if (!previous) return;
    setRedoStack((history) => [...history, structuredClone(timeline)]);
    setUndoStack((history) => history.slice(0, -1));
    setTimeline(previous);
    setDirty(true);
    setSaveState("unsaved");
  }, [timeline, undoStack]);

  const redo = useCallback(() => {
    const next = redoStack.at(-1);
    if (!next) return;
    setUndoStack((history) => [...history, structuredClone(timeline)]);
    setRedoStack((history) => history.slice(0, -1));
    setTimeline(next);
    setDirty(true);
    setSaveState("unsaved");
  }, [redoStack, timeline]);

  const authenticateUser = async () => {
    setError("");
    try {
      const nextToken = await authenticate(baseUrl, email, password, createAccount);
      writeStoredToken(nextToken);
    } catch (authError) {
      setError(responseMessage(authError));
    }
  };

  const saveCurrentTimeline = async () => {
    if (!dirty) return true;
    if (!token || !projectId) return false;
    const snapshot = timelineRef.current;
    setSaveState("saving");
    try {
      await saveTimeline(baseUrl, token, projectId, snapshot);
      if (timelineRef.current !== snapshot) {
        setSaveState("unsaved");
        setError("The timeline changed while saving. Save the latest edits before continuing.");
        return false;
      }
      setDirty(false);
      setSaveState("saved");
      return true;
    } catch (saveError) {
      setError(responseMessage(saveError));
      setSaveState("error");
      return false;
    }
  };

  const makeProject = async (name: string) => {
    if (!name.trim() || !token) return;
    try {
      if (!(await saveCurrentTimeline())) return;
      const project = await createStudioProject(baseUrl, token, name.trim());
      await refreshLibrary(token);
      setPlaying(false);
      setProjectId(project.id);
      setProjectDialogOpen(false);
      setProjectName("");
      setError("");
    } catch (projectError) {
      setError(responseMessage(projectError));
    }
  };

  const changeProject = async (nextProjectId: string) => {
    if (!nextProjectId || nextProjectId === projectId) return;
    if (!(await saveCurrentTimeline())) return;
    setPlaying(false);
    setProjectId(nextProjectId);
  };

  const addAsset = (asset: MediaAsset) => {
    const trackType: TimelineTrackType = asset.media_type === "audio"
      ? "audio"
      : asset.media_type === "image" ? "overlay" : "video";
    const durationSeconds = Math.max(1, Math.min(60, asset.duration_seconds ?? 5));
    const clip: TimelineClip = {
      id: freshId(),
      media_asset_id: asset.id,
      start: Math.max(0, ...timeline.tracks.flatMap((track) =>
        track.type === trackType ? track.clips.map((item) => item.start + item.duration) : [])),
      duration: durationSeconds,
      source_start: 0,
      source_end: asset.duration_seconds ?? null,
      label: asset.name,
    };
    editTimeline((current) => {
      const available = current.tracks.find((track) => track.type === trackType && !track.locked);
      if (available) {
        return {
          ...current,
          tracks: current.tracks.map((track) => track.id === available.id
            ? { ...track, clips: [...track.clips, clip] }
            : track),
        };
      }
      const track: TimelineTrack = {
        id: freshId(),
        name: `${trackType[0].toUpperCase()}${current.tracks.length + 1}`,
        type: trackType,
        muted: false,
        locked: false,
        volume: 1,
        clips: [clip],
      };
      return { ...current, tracks: [...current.tracks, track] };
    });
    setSelectedClip(clip.id);
  };

  const addTextClip = (text: string, preset: TitlePreset = titlePreset) => {
    if (!text.trim()) return;
    const config = titlePresets[preset];
    const clip: TimelineClip = {
      id: freshId(),
      media_asset_id: null,
      start: playhead,
      duration: 3,
      source_start: 0,
      source_end: null,
      text: text.trim(),
      label: config.label,
      position_x: config.position_x,
      position_y: config.position_y,
      fade_in: config.fade_in,
      fade_out: config.fade_out,
      text_style: { ...DEFAULT_TIMELINE_TEXT_STYLE, ...config.style },
    };
    editTimeline((current) => ({
      ...current,
      tracks: current.tracks.some((item) => item.type === "overlay" && !item.locked)
        ? current.tracks.map((item) => item.type === "overlay" && !item.locked
          ? { ...item, clips: [...item.clips, clip] }
          : item)
        : [...current.tracks, {
          id: freshId(), name: "O1", type: "overlay", muted: false, locked: false, volume: 1, clips: [clip],
        }],
    }));
    setSelectedClip(clip.id);
  };

  const addSubtitleClip = (text: string, start = playhead, duration = 3) => {
    if (!text.trim()) return;
    const clip: TimelineClip = {
      id: freshId(),
      media_asset_id: null,
      start,
      duration,
      source_start: 0,
      source_end: null,
      text: text.trim(),
      label: text.trim().slice(0, 80),
      position_x: 0.5,
      position_y: 0.88,
      text_style: {
        ...DEFAULT_TIMELINE_TEXT_STYLE,
        font_size: 36,
        background_opacity: 0.6,
        width: 0.86,
      },
    };
    editTimeline((current) => ({
      ...current,
      tracks: current.tracks.some((item) => item.type === "subtitle" && !item.locked)
        ? current.tracks.map((item) => item.type === "subtitle" && !item.locked
          ? { ...item, clips: [...item.clips, clip] }
          : item)
        : [...current.tracks, {
          id: freshId(), name: "T1", type: "subtitle", muted: false, locked: false, volume: 1, clips: [clip],
        }],
    }));
    setSelectedClip(clip.id);
  };

  const importSubtitles = async (file?: File) => {
    if (!file || !projectId || !token) return;
    setSubtitleImporting(true);
    setError("");
    try {
      const cues = await importSubtitleFile(baseUrl, token, projectId, file);
      if (timeline.tracks.reduce((total, track) => total + track.clips.length, 0) + cues.length > 500) {
        throw new Error("Importing these subtitles would exceed the 500-clip timeline limit.");
      }
      const imported = cues.map((cue: SubtitleCue) => ({
        id: freshId(),
        media_asset_id: null,
        start: cue.start,
        duration: cue.duration,
        source_start: 0,
        source_end: null,
        text: cue.text,
        label: cue.text.slice(0, 80),
        position_x: 0.5,
        position_y: 0.88,
        text_style: {
          ...DEFAULT_TIMELINE_TEXT_STYLE,
          font_size: 36,
          background_opacity: 0.6,
          width: 0.86,
        },
      }));
      editTimeline((current) => current.tracks.some((track) => track.type === "subtitle" && !track.locked)
        ? {
          ...current,
          tracks: current.tracks.map((track) => track.type === "subtitle" && !track.locked
            ? { ...track, clips: [...track.clips, ...imported] }
            : track),
        }
        : {
          ...current,
          tracks: [...current.tracks, {
            id: freshId(), name: "T1", type: "subtitle", muted: false, locked: false, volume: 1, clips: imported,
          }],
        });
      setSelectedClip(imported[0]?.id ?? "");
      setActivePanel("Text");
      setError("");
    } catch (importError) {
      setError(responseMessage(importError));
    } finally {
      setSubtitleImporting(false);
      if (subtitleFileInputRef.current) subtitleFileInputRef.current.value = "";
    }
  };

  const exportSubtitles = async (format: "srt" | "vtt") => {
    if (!projectId || !(await saveCurrentTimeline())) return;
    try {
      const blob = await downloadSubtitles(baseUrl, token, projectId, format);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `subtitles.${format}`;
      link.click();
      URL.revokeObjectURL(url);
      setError("");
    } catch (exportError) {
      setError(responseMessage(exportError));
    }
  };

  const patchSelectedTextStyle = (changes: Partial<TimelineTextStyle>) => {
    if (!selected?.clip.text_style || selected.track.locked) return;
    patchSelected({ text_style: { ...selected.clip.text_style, ...changes } });
  };

  const proposeTextFit = async (operation: TimelineTextFitOperation) => {
    if (!selectedTextClip || !selected || !projectId || !token || selected.track.locked) return;
    const source = timelineRef.current;
    setTextFitLoading(true);
    setTextFitError("");
    setTextFitProposal(null);
    try {
      const result = await proposeTimelineTextFit(
        baseUrl,
        token,
        projectId,
        source,
        selected.clip.id,
        operation,
        exportPreset,
        minimumTextFontSize,
      );
      if (timelineRef.current !== source) {
        throw new Error("The timeline changed while preparing this fit. Request a new proposal.");
      }
      setTextFitProposal({ ...result, source });
    } catch (fitError) {
      setTextFitError(responseMessage(fitError));
    } finally {
      setTextFitLoading(false);
    }
  };

  const applyTextFitProposal = () => {
    if (!textFitProposal || timelineRef.current !== textFitProposal.source) return;
    const updatedTextClip = textFitProposal.timeline.tracks
      .flatMap((track) => track.clips)
      .find((clip) => clip.id === selectedClip);
    editTimeline(() => textFitProposal.timeline);
    if (updatedTextClip) setSelectedClip(updatedTextClip.id);
    setTextFitProposal(null);
    setTextFitError("");
  };

  const splitSelected = () => {
    if (!selected || selected.track.locked || playhead <= selected.clip.start + 0.05
      || playhead >= selected.clip.start + selected.clip.duration - 0.05) return;
    const beforeDuration = playhead - selected.clip.start;
    const after: TimelineClip = {
      ...selected.clip,
      id: freshId(),
      start: playhead,
      duration: selected.clip.duration - beforeDuration,
      source_start: selected.clip.media_asset_id
        ? selected.clip.source_start + beforeDuration
        : selected.clip.source_start,
      text_style: selected.clip.text_style ? { ...selected.clip.text_style } : undefined,
    };
    editTimeline((current) => ({
      ...current,
      tracks: current.tracks.map((track) => track.id === selected.track.id
        ? {
          ...track,
          clips: track.clips.flatMap((clip) => clip.id === selected.clip.id
            ? [{ ...clip, duration: beforeDuration }, after]
            : [clip]),
        }
        : track),
    }));
    setSelectedClip(after.id);
  };

  const combineSelectedSubtitle = () => {
    if (!selected || selected.track.type !== "subtitle" || !selectedSubtitleNext || selected.track.locked) return;
    const end = Math.max(
      selected.clip.start + selected.clip.duration,
      selectedSubtitleNext.start + selectedSubtitleNext.duration,
    );
    const combined: TimelineClip = {
      ...selected.clip,
      duration: end - selected.clip.start,
      text: `${selected.clip.text?.trim() ?? ""}\n${selectedSubtitleNext.text?.trim() ?? ""}`.trim(),
      label: `${selected.clip.text?.trim() ?? ""} ${selectedSubtitleNext.text?.trim() ?? ""}`.trim().slice(0, 80),
      text_style: selected.clip.text_style ? { ...selected.clip.text_style } : undefined,
    };
    editTimeline((current) => ({
      ...current,
      tracks: current.tracks.map((track) => track.id === selected.track.id
        ? {
          ...track,
          clips: track.clips
            .filter((clip) => clip.id !== selectedSubtitleNext.id)
            .map((clip) => clip.id === selectedClip ? combined : clip),
        }
        : track),
    }));
  };

  const patchSelected = (changes: Partial<TimelineClip>) => {
    if (!selected || selected.track.locked) return;
    editTimeline((current) => ({
      ...current,
      tracks: current.tracks.map((track) => track.id === selected.track.id
        ? {
          ...track,
          clips: track.clips.map((clip) => clip.id === selectedClip ? { ...clip, ...changes } : clip),
        }
        : track),
    }));
  };

  const addSelectedEffect = () => {
    if (!selected || selected.track.locked || !["video", "overlay"].includes(selected.track.type)) return;
    const config = effectLimits[newEffectType];
    const effect: TimelineEffect = {
      id: freshId(),
      type: newEffectType,
      enabled: true,
      value: config.initial,
    };
    patchSelected({ effects: [...(selected.clip.effects ?? []), effect] });
  };

  const patchSelectedEffect = (effectId: string, changes: Partial<TimelineEffect>) => {
    if (!selected || selected.track.locked) return;
    patchSelected({
      effects: (selected.clip.effects ?? []).map((effect) =>
        effect.id === effectId ? { ...effect, ...changes } : effect),
    });
  };

  const removeSelectedEffect = (effectId: string) => {
    patchSelected({
      effects: (selected?.clip.effects ?? []).filter((effect) => effect.id !== effectId),
    });
  };

  const removeSelected = useCallback(() => {
    if (!selectedClip || selectedTrackLocked) return;
    editTimeline((current) => ({
      ...current,
      tracks: current.tracks.map((track) => ({
        ...track,
        clips: track.clips.filter((clip) => clip.id !== selectedClip),
      })),
    }));
    setSelectedClip("");
  }, [editTimeline, selectedClip, selectedTrackLocked]);

  const duplicateSelected = () => {
    if (!selected || selected.track.locked) return;
    const duplicate: TimelineClip = {
      ...selected.clip,
      id: freshId(),
      start: selected.clip.start + selected.clip.duration,
      keyframes: selected.clip.keyframes?.map((keyframe) => ({ ...keyframe })),
    };
    editTimeline((current) => ({
      ...current,
      tracks: current.tracks.map((track) => track.id === selected.track.id
        ? { ...track, clips: [...track.clips, duplicate] }
        : track),
    }));
    setSelectedClip(duplicate.id);
  };

  const trimStartToPlayhead = () => {
    if (!selected || playhead <= selected.clip.start
      || playhead >= selected.clip.start + selected.clip.duration) return;
    const offset = playhead - selected.clip.start;
    patchSelected({
      start: playhead,
      duration: selected.clip.duration - offset,
      source_start: selected.clip.source_start + offset,
    });
  };

  const trimEndToPlayhead = () => {
    if (!selected || playhead <= selected.clip.start
      || playhead >= selected.clip.start + selected.clip.duration) return;
    patchSelected({ duration: playhead - selected.clip.start });
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLElement
        && (event.target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(event.target.tagName))) return;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) redo();
        else undo();
      } else if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "y") {
        event.preventDefault();
        redo();
      } else if (event.key === "Delete" || event.key === "Backspace") {
        removeSelected();
      } else if (event.code === "Space") {
        event.preventDefault();
        togglePlayback();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [redo, removeSelected, togglePlayback, undo]);

  const addTrack = (type: TimelineTrackType) => {
    editTimeline((current) => ({
      ...current,
      tracks: [...current.tracks, {
        id: freshId(),
        name: `${type[0].toUpperCase()}${current.tracks.length + 1}`,
        type,
        muted: false,
        locked: false,
        volume: 1,
        clips: [],
      }],
    }));
  };

  const toggleTrack = (trackId: string, key: "muted" | "locked") => {
    editTimeline((current) => ({
      ...current,
      tracks: current.tracks.map((track) => track.id === trackId ? { ...track, [key]: !track[key] } : track),
    }));
  };

  const setTrackVolume = (trackId: string, volume: number) => {
    editTimeline((current) => ({
      ...current,
      tracks: current.tracks.map((track) => track.id === trackId ? { ...track, volume } : track),
    }));
  };

  const moveTrack = (trackId: string, direction: -1 | 1) => {
    editTimeline((current) => {
      const index = current.tracks.findIndex((track) => track.id === trackId);
      const target = index + direction;
      if (index < 0 || target < 0 || target >= current.tracks.length) return current;
      const tracks = [...current.tracks];
      const [track] = tracks.splice(index, 1);
      if (!track) return current;
      tracks.splice(target, 0, track);
      return { ...current, tracks };
    });
  };

  const addSelectedKeyframe = () => {
    if (!selected || selected.track.locked) return;
    const time = Math.max(0, Math.min(selected.clip.duration, playhead - selected.clip.start));
    const keyframe = { time, property: keyframeProperty, value: keyframeValue, interpolation: "linear" as const };
    patchSelected({
      keyframes: [
        ...(selected.clip.keyframes ?? []).filter((item) =>
          item.property !== keyframeProperty || Math.abs(item.time - time) > 0.001),
        keyframe,
      ].sort((left, right) => left.time - right.time),
    });
  };

  const startDrag = (event: React.PointerEvent<HTMLButtonElement>, track: TimelineTrack, clip: TimelineClip) => {
    if (track.locked) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragState.current = {
      trackId: track.id,
      clipId: clip.id,
      pointerX: event.clientX,
      initialStart: clip.start,
      currentTrackId: track.id,
      initialTimeline: structuredClone(timelineRef.current),
      changed: false,
    };
  };

  const moveDrag = (event: React.PointerEvent<HTMLButtonElement>) => {
    const drag = dragState.current;
    if (!drag) return;
    const targetRow = document.elementFromPoint(event.clientX, event.clientY)
      ?.closest<HTMLElement>("[data-editor-track-id]");
    const targetTrackId = targetRow?.dataset.editorTrackId ?? drag.currentTrackId;
    const seconds = (event.clientX - drag.pointerX) / zoom;
    const frameRate = timelineRef.current.frame_rate;
    const snapped = Math.max(0, Math.round((drag.initialStart + seconds) * frameRate) / frameRate);
    const current = timelineRef.current;
    const sourceTrack = current.tracks.find((track) => track.id === drag.currentTrackId);
    const targetTrack = current.tracks.find((track) => track.id === targetTrackId);
    const clip = sourceTrack?.clips.find((item) => item.id === drag.clipId);
    if (!sourceTrack || !targetTrack || !clip || targetTrack.locked) return;
    const mediaType = clip.text
      ? "text"
      : clip.media_asset_id
      ? assetById.get(clip.media_asset_id)?.media_type
      : undefined;
    const compatible = mediaType === "text"
      ? targetTrack.type === "subtitle" || targetTrack.type === "overlay"
      : targetTrack.type === "video"
        ? mediaType === "video"
        : targetTrack.type === "audio"
          ? mediaType === "audio" || mediaType === "video"
          : targetTrack.type === "overlay"
            ? mediaType === "image" || mediaType === "video"
            : false;
    if (!compatible) return;
    const movedClip = { ...clip, start: snapped };
    const next = {
      ...current,
      tracks: sourceTrack.id === targetTrack.id
        ? current.tracks.map((track) => track.id === sourceTrack.id
          ? { ...track, clips: track.clips.map((item) => item.id === clip.id ? movedClip : item) }
          : track)
        : current.tracks.map((track) => {
          if (track.id === sourceTrack.id) {
            return { ...track, clips: track.clips.filter((item) => item.id !== clip.id) };
          }
          if (track.id === targetTrack.id) return { ...track, clips: [...track.clips, movedClip] };
          return track;
        }),
    };
    timelineRef.current = next;
    setTimeline(next);
    if (sourceTrack.id !== targetTrack.id) drag.currentTrackId = targetTrack.id;
    if (snapped !== drag.initialStart || targetTrackId !== drag.trackId) drag.changed = true;
    setDirty(true);
    setSaveState("unsaved");
  };

  const finishDrag = () => {
    const drag = dragState.current;
    if (!drag) return;
    dragState.current = null;
    if (!drag.changed) return;
    setUndoStack((history) => [...history.slice(-39), drag.initialTimeline]);
    setRedoStack([]);
  };

  const previewTimeline = () => {
    const first = [...allVideoClips, ...allAudioClips]
      .sort((left, right) => left.clip.start - right.clip.start)[0];
    if (!first) return;
    seekTo(first.clip.start);
    startPlayback();
  };

  const watchExport = async (jobId: string) => {
    setExportJobId(jobId);
    setExporting(true);
    setError("");
    try {
      for (let attempt = 0; attempt < 900; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        const status = await getTimelineExport(baseUrl, token, jobId);
        setExportJobStatus(status.status);
        setExportProgress(status.progress);
        setExportMessage(`Export ${status.status} · ${status.progress}%`);
        if (status.status === "failed") {
          setExportRetryCount(status.retry_count ?? exportRetryCount);
          setExportMaxRetries(status.max_retries ?? exportMaxRetries);
          throw new Error(status.error_message ?? "Export failed.");
        }
        if (status.status === "cancelled") {
          setExportMessage("Export cancelled.");
          return;
        }
        if (status.status === "completed") {
          const blob = await downloadTimelineExport(baseUrl, token, jobId);
          const url = URL.createObjectURL(blob);
          const link = document.createElement("a");
          link.href = url;
          link.download = `creator-studio-${jobId}.mp4`;
          link.click();
          window.setTimeout(() => URL.revokeObjectURL(url), 1000);
          setExportMessage("Export downloaded.");
          return;
        }
      }
      throw new Error("Export is still processing. Check the export status later.");
    } catch (exportError) {
      setError(responseMessage(exportError));
      setExportMessage(exportJobStatus === "cancelled" ? "Export cancelled." : "Export failed.");
    } finally {
      setExporting(false);
    }
  };

  const exportTimeline = async () => {
    if (!token || !projectId || exporting) return;
    setExporting(true);
    setError("");
    setExportMessage("Queueing export…");
    try {
      const exportSnapshot = timelineRef.current;
      if (dirty || saveState !== "saved") {
        await saveTimeline(baseUrl, token, projectId, exportSnapshot);
        if (timelineRef.current !== exportSnapshot) {
          throw new Error("The timeline changed while saving. Save the latest edits before exporting.");
        }
        setDirty(false);
        setSaveState("saved");
      }
      const validation = await validateTimelineText(
        baseUrl,
        token,
        projectId,
        exportSnapshot,
        exportPreset,
      );
      setTextValidationIssues(validation.issues);
      setTextValidationError("");
      const blockingIssues = validation.issues.filter((issue) => issue.severity === "error");
      if (blockingIssues.length) {
        setActivePanel("Text");
        setExportMessage(
          `Export blocked: fix ${blockingIssues.length} text issue${blockingIssues.length === 1 ? "" : "s"} first.`,
        );
        return;
      }
      const queued = await queueTimelineExport(
        baseUrl,
        token,
        projectId,
        [],
        exportPreset,
      );
      if (!queued.job_id) throw new Error("The backend did not return an export job ID.");
      setExportRetryCount(0);
      setExportMaxRetries(2);
      setExportJobStatus("queued");
      const warningCount = validation.issues.filter((issue) => issue.severity === "warning").length;
      setExportMessage(warningCount
        ? `Export queued with ${warningCount} text warning${warningCount === 1 ? "" : "s"}.`
        : "Export queued.");
      await watchExport(queued.job_id);
    } catch (exportError) {
      setError(responseMessage(exportError));
      setExportMessage("Export failed.");
    } finally {
      setExporting(false);
    }
  };

  const cancelExport = async () => {
    if (!token || !exportJobId || !exporting) return;
    try {
      const status = await cancelTimelineExport(baseUrl, token, exportJobId);
      setExportJobStatus(status.status);
      setExportMessage(status.status === "cancelled"
        ? "Export cancelled."
        : "Cancellation requested…");
    } catch (cancelError) {
      setError(responseMessage(cancelError));
    }
  };

  const retryExport = async () => {
    if (!token || !exportJobId || exporting) return;
    try {
      const retried = await retryTimelineExport(baseUrl, token, exportJobId);
      const nextJobId = retried.id ?? retried.job_id;
      if (!nextJobId) throw new Error("The backend did not return the retried job ID.");
      setExportRetryCount(retried.retry_count ?? exportRetryCount + 1);
      setExportMaxRetries(retried.max_retries ?? exportMaxRetries);
      setExportJobStatus("queued");
      setExportMessage("Export retry queued.");
      await watchExport(nextJobId);
    } catch (retryError) {
      setError(responseMessage(retryError));
    }
  };

  const importFile = async (file?: File) => {
    if (!file || !token) return;
    setUploading(true);
    setUploadProgress(0);
    setError("");
    try {
      const uploaded = await uploadMedia(
        baseUrl,
        token,
        file,
        setUploadProgress,
        projectId || undefined,
      );
      setAssets((current) => [uploaded.asset, ...current]);
      setMediaJobs((current) => ({
        ...current,
        [uploaded.asset.id]: {
          id: uploaded.job_id,
          job_type: "media_process",
          status: "queued",
          progress: 0,
          error_message: null,
          retry_count: 0,
          max_retries: 2,
          cancellation_requested: false,
        },
      }));
      setActivePanel(uploaded.asset.media_type === "audio" ? "Audio" : "Media");
    } catch (uploadError) {
      setError(responseMessage(uploadError));
    } finally {
      setUploading(false);
      setUploadProgress(0);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const manageMediaJob = async (asset: MediaAsset, action: "retry" | "cancel") => {
    if (!token) return;
    const jobId = asset.metadata_json?.processing_job_id;
    if (!jobId) return;
    setError("");
    try {
      const job = action === "retry"
        ? await retryMediaJob(baseUrl, token, jobId)
        : await cancelMediaJob(baseUrl, token, jobId);
      setMediaJobs((current) => ({ ...current, [asset.id]: job }));
    } catch (jobError) {
      setError(responseMessage(jobError));
    }
  };

  const saveNow = async () => {
    if (!token || !projectId) return;
    setSaveState("saving");
    try {
      await saveTimeline(baseUrl, token, projectId, timeline);
      if (timelineRef.current === timeline) {
        setDirty(false);
        setSaveState("saved");
      }
    } catch (saveError) {
      setError(responseMessage(saveError));
      setSaveState("error");
    }
  };

  const logOut = () => {
    writeStoredToken(null);
    setPlaying(false);
    setProjects([]);
    setAssets([]);
    setProjectId("");
    setLoadedProjectId("");
    playheadRef.current = 0;
    setPlayhead(0);
    setError("");
  };

  if (!token) {
    return (
      <Card className="editor-connect-card">
        <div className="editor-connect-icon"><Clapperboard size={23} /></div>
        <div className="eyebrow">VIDEO STUDIO</div>
        <h2>Connect to your local workspace</h2>
        <p>Sign in to load your projects and media from the local FastAPI backend. No AI processing is used here.</p>
        <Field label="Backend URL"><TextInput value={baseUrl} onChange={(event) => writeStoredBackendUrl(event.target.value)} /></Field>
        <Field label="Email"><TextInput autoComplete="email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></Field>
        <Field label="Password"><TextInput autoComplete={createAccount ? "new-password" : "current-password"} type="password" value={password} onChange={(event) => setPassword(event.target.value)} /></Field>
        <label className="editor-checkbox"><input checked={createAccount} onChange={(event) => setCreateAccount(event.target.checked)} type="checkbox" /> Create a new account</label>
        {error && <p className="editor-error" role="alert">{error}</p>}
        <Button onClick={() => void authenticateUser()} variant="primary">Connect</Button>
      </Card>
    );
  }

  return (
    <div className="video-editor-workspace">
      <div className="video-editor-topbar">
        <div className="video-editor-project">
          <label htmlFor="editor-project">Project</label>
          <SelectInput id="editor-project" onChange={(event) => void changeProject(event.target.value)} value={projectId}>
            {projects.length === 0 && <option value="">No projects</option>}
            {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
          </SelectInput>
          <Button aria-label="Create project" onClick={() => setProjectDialogOpen(true)} size="sm"><Plus size={15} /></Button>
        </div>
        <div className="video-editor-actions">
          <span className={`save-indicator save-${saveState}`}><Check size={13} /> {saveState === "saving" ? "Saving" : saveState === "error" ? "Save error" : dirty ? "Unsaved" : "Saved"}</span>
          <Button aria-label="Undo" disabled={!undoStack.length} onClick={undo} size="sm"><Undo2 size={15} /></Button>
          <Button aria-label="Redo" disabled={!redoStack.length} onClick={redo} size="sm"><Redo2 size={15} /></Button>
          <Button disabled={!projectId} icon={<Check size={14} />} onClick={() => void saveNow()} size="sm">Save</Button>
          <Button disabled={!allVideoClips.length && !allAudioClips.length} icon={<Play size={14} />} onClick={previewTimeline} size="sm">Preview</Button>
          <SelectInput
            aria-label="Export resolution"
            disabled={exporting}
            onChange={(event) => setExportPreset(event.target.value as "720p" | "1080p" | "4k")}
            value={exportPreset}
          >
            <option value="720p">720p</option>
            <option value="1080p">1080p</option>
            <option value="4k">4K</option>
          </SelectInput>
          <Button disabled={!projectId || !allVideoClips.length || exporting} icon={<Download size={14} />} onClick={() => void exportTimeline()} size="sm" variant="primary">Export MP4</Button>
          {exporting && <Button onClick={() => void cancelExport()} size="sm">Cancel export</Button>}
          {!exporting && (exportJobStatus === "failed" || exportJobStatus === "cancelled") &&
            exportRetryCount < exportMaxRetries && (
            <Button onClick={() => void retryExport()} size="sm">Retry export</Button>
          )}
          {!exporting && exportJobId && exportJobStatus === "processing" && (
            <Button onClick={() => void watchExport(exportJobId)} size="sm">Check export</Button>
          )}
          <Button onClick={logOut} size="sm">Sign out</Button>
        </div>
      </div>
      {error && <div className="editor-inline-error" role="alert">{error}<button onClick={() => setError("")} type="button">Dismiss</button></div>}
      {loadedProjectId === projectId && projectHasText
        && (textValidationLoading || textValidationError || textValidationIssues.length > 0) && (
        <section aria-label="Project text validation" className="editor-text-validation">
          <div className="editor-text-validation-heading">
            <strong>Text pre-export check</strong>
            <span>{textValidationLoading ? "Checking export fonts and layout…" : textValidationError
              ? "Validation unavailable"
              : `${blockingTextIssueCount} blocking · ${warningTextIssueCount} warnings`}</span>
          </div>
          {textValidationError && <p role="alert">{textValidationError}</p>}
          {textValidationIssues.map((issue) => (
            <button
              aria-label={`Go to ${issue.severity}: ${issue.message}`}
              className={`editor-text-issue editor-text-issue-${issue.severity}`}
              key={`${issue.clip_id}-${issue.code}-${issue.message}`}
              onClick={() => navigateToTextIssue(issue.clip_id)}
              type="button"
            >
              <span>{issue.severity === "error" ? "Blocking" : "Warning"} · {issue.track_name}</span>
              <strong>{issue.message}</strong>
              <small>{issue.recommendation}{issue.alternatives.length
                ? ` Alternatives: ${issue.alternatives.join(", ")}.`
                : ""}</small>
            </button>
          ))}
        </section>
      )}
      {!projectId ? (
        <div className="editor-empty-state">
          <Clapperboard size={27} /><h2>Create a project to begin</h2>
          <p>Video edits and exports are saved to a project in your local backend.</p>
          <Button onClick={() => setProjectDialogOpen(true)} variant="primary">New project</Button>
        </div>
      ) : (
        <>
          <div className="video-editor-main">
            <Card className="editor-media-panel">
              <div
                aria-label="Editor assets"
                className="editor-panel-tabs"
                onKeyDown={(event) => {
                  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
                  const tabs = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
                  const index = tabs.indexOf(document.activeElement as HTMLButtonElement);
                  const direction = event.key === "ArrowRight" ? 1 : -1;
                  const nextIndex = (index + direction + tabs.length) % tabs.length;
                  event.preventDefault();
                  tabs[nextIndex]?.focus();
                  const nextPanel = panelNames[nextIndex];
                  if (nextPanel) setActivePanel(nextPanel);
                }}
                role="tablist"
              >
                {panelNames.map((name, index) => {
                  const Icon = panelIcons[index];
                  return <button aria-selected={activePanel === name} className={activePanel === name ? "active" : ""} key={name} onClick={() => setActivePanel(name)} role="tab" type="button"><Icon size={14} /><span>{name}</span></button>;
                })}
              </div>
              <div className="editor-library-heading"><strong>{activePanel}</strong><span>{activePanel === "Text" ? "Editable" : "Local assets"}</span></div>
              {activePanel === "Text" ? (
                <div className="editor-text-panel">
                  <div className="editor-title-actions">
                    <Field label="Title preset">
                      <SelectInput
                        aria-label="Title preset"
                        onChange={(event) => setTitlePreset(event.target.value as TitlePreset)}
                        value={titlePreset}
                      >
                        {Object.entries(titlePresets).map(([key, preset]) => (
                          <option key={key} value={key}>{preset.label}</option>
                        ))}
                      </SelectInput>
                    </Field>
                    <Button onClick={() => addTextClip("Your title")} size="sm"><Plus size={13} /> Add title</Button>
                    <Button onClick={() => setSubtitleDialogOpen(true)} size="sm"><Plus size={13} /> Add subtitle</Button>
                  </div>
                  <div className="editor-subtitle-file-actions">
                    <input
                      accept=".srt,.vtt,text/vtt,application/x-subrip"
                      aria-label="Import SRT or VTT subtitles"
                      className="visually-hidden"
                      disabled={subtitleImporting}
                      onChange={(event) => void importSubtitles(event.target.files?.[0])}
                      ref={subtitleFileInputRef}
                      type="file"
                    />
                    <Button disabled={subtitleImporting || !projectId} onClick={() => subtitleFileInputRef.current?.click()} size="sm">
                      <Upload size={13} /> {subtitleImporting ? "Importing…" : "Import SRT/VTT"}
                    </Button>
                    <Button disabled={!projectId || !subtitleEntries.length} onClick={() => void exportSubtitles("srt")} size="sm">Export SRT</Button>
                    <Button disabled={!projectId || !subtitleEntries.length} onClick={() => void exportSubtitles("vtt")} size="sm">Export VTT</Button>
                  </div>
                  <p className="editor-hint">Subtitle entries are editable timeline clips. Speech recognition and translation are not part of this editor.</p>
                  {selectedTextClip && selected ? (
                    <div className="editor-text-editor">
                      <div className="editor-effect-selection">
                        <strong>{selected.clip.label ?? (selected.track.type === "subtitle" ? "Subtitle" : "Title")}</strong>
                        <Badge>{selected.track.name}</Badge>
                      </div>
                      {selectedTextIssues.map((issue) => (
                        <div
                          className={`editor-text-issue editor-text-issue-${issue.severity}`}
                          key={`${issue.code}-${issue.message}`}
                        >
                          <strong>{issue.severity === "error" ? "Export blocked" : "Review suggested"} · {issue.message}</strong>
                          <small>{issue.recommendation}{issue.alternatives.length
                            ? ` Available worker fonts: ${issue.alternatives.join(", ")}.`
                            : ""}</small>
                        </div>
                      ))}
                      <label className="editor-text-content">
                        <span>Text content</span>
                        <textarea
                          aria-label="Text content"
                          disabled={selected.track.locked}
                          maxLength={10_000}
                          onChange={(event) => patchSelected({
                            text: event.target.value,
                            label: event.target.value.trim().slice(0, 80),
                          })}
                          value={selected.clip.text ?? ""}
                        />
                      </label>
                      <div className="editor-text-fields">
                        <Field label="Font family">
                          <SelectInput aria-label="Font family" disabled={selected.track.locked} onChange={(event) => patchSelectedTextStyle({ font_family: event.target.value as TimelineTextStyle["font_family"] })} value={selectedTextStyle.font_family}>
                            <option value="sans-serif">Sans serif</option><option value="serif">Serif</option><option value="monospace">Monospace</option>
                          </SelectInput>
                        </Field>
                        <Field label="Font size">
                          <TextInput aria-label="Font size" disabled={selected.track.locked} max="300" min="10" onChange={(event) => patchSelectedTextStyle({ font_size: Math.max(10, Math.min(300, Number(event.target.value) || 10)) })} type="number" value={selectedTextStyle.font_size} />
                        </Field>
                        <Field label="Font weight">
                          <SelectInput aria-label="Font weight" disabled={selected.track.locked} onChange={(event) => patchSelectedTextStyle({ font_weight: event.target.value as TimelineTextStyle["font_weight"] })} value={selectedTextStyle.font_weight}>
                            <option value="normal">Regular</option><option value="bold">Bold</option>
                          </SelectInput>
                        </Field>
                        <Field label="Font style">
                          <SelectInput aria-label="Font style" disabled={selected.track.locked} onChange={(event) => patchSelectedTextStyle({ font_style: event.target.value as TimelineTextStyle["font_style"] })} value={selectedTextStyle.font_style}>
                            <option value="normal">Normal</option><option value="italic">Italic</option>
                          </SelectInput>
                        </Field>
                        <Field label="Alignment">
                          <SelectInput aria-label="Text alignment" disabled={selected.track.locked} onChange={(event) => patchSelectedTextStyle({ alignment: event.target.value as TimelineTextStyle["alignment"] })} value={selectedTextStyle.alignment}>
                            <option value="left">Left</option><option value="center">Center</option><option value="right">Right</option>
                          </SelectInput>
                        </Field>
                        <Field label="Vertical alignment">
                          <SelectInput aria-label="Vertical alignment" disabled={selected.track.locked} onChange={(event) => patchSelectedTextStyle({ vertical_alignment: event.target.value as TimelineTextStyle["vertical_alignment"] })} value={selectedTextStyle.vertical_alignment}>
                            <option value="top">Top</option><option value="middle">Middle</option><option value="bottom">Bottom</option>
                          </SelectInput>
                        </Field>
                        <label className="editor-color-field">Text color<input aria-label="Text color" disabled={selected.track.locked} onChange={(event) => patchSelectedTextStyle({ color: event.target.value })} type="color" value={selectedTextStyle.color} /></label>
                        <label className="editor-color-field">Background color<input aria-label="Text background color" disabled={selected.track.locked} onChange={(event) => patchSelectedTextStyle({ background_color: event.target.value })} type="color" value={selectedTextStyle.background_color} /></label>
                        <label className="editor-color-field">Outline color<input aria-label="Text outline color" disabled={selected.track.locked} onChange={(event) => patchSelectedTextStyle({ outline_color: event.target.value })} type="color" value={selectedTextStyle.outline_color} /></label>
                        <label className="editor-color-field">Shadow color<input aria-label="Text shadow color" disabled={selected.track.locked} onChange={(event) => patchSelectedTextStyle({ shadow_color: event.target.value })} type="color" value={selectedTextStyle.shadow_color} /></label>
                        <Field label="Background opacity">
                          <TextInput aria-label="Text background opacity" disabled={selected.track.locked} max="1" min="0" onChange={(event) => patchSelectedTextStyle({ background_opacity: Math.max(0, Math.min(1, Number(event.target.value) || 0)) })} step="0.05" type="number" value={selectedTextStyle.background_opacity} />
                        </Field>
                        <Field label="Outline width">
                          <TextInput aria-label="Text outline width" disabled={selected.track.locked} max="20" min="0" onChange={(event) => patchSelectedTextStyle({ outline_width: Math.max(0, Math.min(20, Number(event.target.value) || 0)) })} type="number" value={selectedTextStyle.outline_width} />
                        </Field>
                        <Field label="Shadow blur">
                          <TextInput aria-label="Text shadow blur" disabled={selected.track.locked} max="20" min="0" onChange={(event) => patchSelectedTextStyle({ shadow_blur: Math.max(0, Math.min(20, Number(event.target.value) || 0)) })} type="number" value={selectedTextStyle.shadow_blur} />
                        </Field>
                        <Field label="Text box width">
                          <TextInput aria-label="Text box width" disabled={selected.track.locked} max="1" min="0.1" onChange={(event) => patchSelectedTextStyle({ width: Math.max(0.1, Math.min(1, Number(event.target.value) || 0.1)) })} step="0.05" type="number" value={selectedTextStyle.width} />
                        </Field>
                        <Field label="Layer order">
                          <TextInput aria-label="Text layer order" disabled={selected.track.locked} max="1000" min="-1000" onChange={(event) => patchSelected({ z_index: Math.max(-1000, Math.min(1000, Number(event.target.value) || 0)) })} type="number" value={selected.clip.z_index ?? 0} />
                        </Field>
                        <Field label="Position X">
                          <TextInput aria-label="Text position X" disabled={selected.track.locked} max="1" min="0" onChange={(event) => patchSelected({ position_x: Math.max(0, Math.min(1, Number(event.target.value) || 0)) })} step="0.01" type="number" value={selected.clip.position_x ?? 0.5} />
                        </Field>
                        <Field label="Position Y">
                          <TextInput aria-label="Text position Y" disabled={selected.track.locked} max="1" min="0" onChange={(event) => patchSelected({ position_y: Math.max(0, Math.min(1, Number(event.target.value) || 0)) })} step="0.01" type="number" value={selected.clip.position_y ?? 0.5} />
                        </Field>
                        <Field label="Clip opacity">
                          <TextInput aria-label="Text clip opacity" disabled={selected.track.locked} max="1" min="0" onChange={(event) => patchSelected({ opacity: Math.max(0, Math.min(1, Number(event.target.value) || 0)) })} step="0.05" type="number" value={selected.clip.opacity ?? 1} />
                        </Field>
                        <Field label="Fade in (sec)">
                          <TextInput aria-label="Text fade in" disabled={selected.track.locked} max={selected.clip.duration} min="0" onChange={(event) => patchSelected({ fade_in: Math.max(0, Math.min(selected.clip.duration, Number(event.target.value) || 0)) })} step="0.05" type="number" value={selected.clip.fade_in ?? 0} />
                        </Field>
                        <Field label="Fade out (sec)">
                          <TextInput aria-label="Text fade out" disabled={selected.track.locked} max={selected.clip.duration} min="0" onChange={(event) => patchSelected({ fade_out: Math.max(0, Math.min(selected.clip.duration, Number(event.target.value) || 0)) })} step="0.05" type="number" value={selected.clip.fade_out ?? 0} />
                        </Field>
                      </div>
                      <div className="editor-text-fit-tools">
                        <strong>Text fit tools</strong>
                        <p className="editor-hint">Automatic word wrapping is already used by preview and export. Proposals are checked by the export worker and do not change text until applied.</p>
                        <div className="editor-subtitle-operations">
                          <Button
                            disabled={selected.track.locked || textFitLoading || selectedTextStyle.width >= 1}
                            onClick={() => void proposeTextFit("fit_width")}
                            size="sm"
                          >Fit box width</Button>
                          <Button
                            disabled={selected.track.locked || textFitLoading || selectedTextStyle.font_size <= minimumTextFontSize}
                            onClick={() => void proposeTextFit("shrink")}
                            size="sm"
                          >Shrink to fit</Button>
                          <Button
                            disabled={selected.track.locked || textFitLoading || (selected.clip.text?.trim().split(/\s+/).length ?? 0) < 2}
                            onClick={() => void proposeTextFit("split")}
                            size="sm"
                          >{selected.track.type === "subtitle" ? "Split subtitle at words" : "Split into sequential clips"}</Button>
                        </div>
                        <Field label="Minimum font size for shrink">
                          <TextInput
                            aria-label="Minimum text font size"
                            disabled={selected.track.locked || textFitLoading}
                            max={selectedTextStyle.font_size}
                            min="10"
                            onChange={(event) => setMinimumTextFontSize(Math.max(10, Math.min(
                              selectedTextStyle.font_size,
                              Number(event.target.value) || 10,
                            )))}
                            type="number"
                            value={minimumTextFontSize}
                          />
                        </Field>
                        {textFitLoading && <p role="status">Preparing a render-validated proposal…</p>}
                        {textFitError && <p className="editor-inline-error" role="alert">{textFitError}</p>}
                        {textFitProposal && (() => {
                          const sourceTrack = textFitProposal.source.tracks.find((track) => track.id === selected.track.id);
                          const proposalTrack = textFitProposal.timeline.tracks.find((track) => track.id === selected.track.id);
                          const originalIds = new Set(sourceTrack?.clips.map((clip) => clip.id) ?? []);
                          const proposalClips = (proposalTrack?.clips ?? [])
                            .filter((clip) => clip.id === selected.clip.id || !originalIds.has(clip.id))
                            .sort((left, right) => left.start - right.start);
                          const proposedText = proposalClips.map((clip) => clip.text ?? "").join("");
                          const currentProposal = textFitProposal.source === timeline;
                          return (
                            <div aria-label="Text fit proposal" className="editor-text-fit-proposal" role="status">
                              <strong>Review before applying</strong>
                              <span>Original text</span>
                              <pre>{selected.clip.text}</pre>
                              <span>Proposed text (all characters preserved: {proposedText === selected.clip.text ? "yes" : "no"})</span>
                              <pre>{proposedText}</pre>
                              {proposalClips.map((clip) => (
                                <small key={clip.id}>
                                  {formatTime(clip.start)}–{formatTime(clip.start + clip.duration)}
                                  {clip.text_style?.font_size !== selectedTextStyle.font_size
                                    ? ` · ${clip.text_style?.font_size}px`
                                    : ""}
                                </small>
                              ))}
                              {textFitProposal.warnings.map((warning) => <p key={warning}>{warning}</p>)}
                              {!currentProposal && <p role="alert">Timeline changed. Discard this stale proposal and request it again.</p>}
                              <div className="editor-subtitle-operations">
                                <Button
                                  disabled={!currentProposal}
                                  onClick={applyTextFitProposal}
                                  size="sm"
                                  variant="primary"
                                >Apply proposal</Button>
                                <Button onClick={() => setTextFitProposal(null)} size="sm">Discard</Button>
                              </div>
                            </div>
                          );
                        })()}
                      </div>
                      {selected.track.type === "subtitle" && (
                        <div className="editor-subtitle-operations">
                          <Button disabled={selected.track.locked || playhead <= selected.clip.start + 0.05 || playhead >= selected.clip.start + selected.clip.duration - 0.05} onClick={splitSelected} size="sm">Split at playhead</Button>
                          <Button disabled={selected.track.locked || !selectedSubtitleNext} onClick={combineSelectedSubtitle} size="sm">Combine with next</Button>
                        </div>
                      )}
                    </div>
                  ) : <p className="editor-empty-copy">Select a title or subtitle clip in the timeline to edit its content and style.</p>}
                  <div className="editor-subtitle-list">
                    <strong>Subtitle entries <span>{subtitleEntries.length}</span></strong>
                    {subtitleEntries.map(({ clip }) => (
                      <button
                        aria-label={`Select subtitle ${clip.text} at ${clip.start.toFixed(2)} seconds`}
                        className={clip.id === selectedClip ? "selected" : ""}
                        key={clip.id}
                        onClick={() => { setSelectedClip(clip.id); seekTo(clip.start); }}
                        type="button"
                      >
                        <span>{formatTime(clip.start)}–{formatTime(clip.start + clip.duration)}</span>
                        <small>{clip.text}</small>
                      </button>
                    ))}
                    {!subtitleEntries.length && <p className="editor-empty-copy">No subtitles yet. Add a cue or import an SRT/VTT file.</p>}
                  </div>
                  {error && <p className="editor-inline-error" role="alert">{error}</p>}
                  <span className={`save-indicator save-${saveState}`} role="status">{saveState === "saving" ? "Saving text…" : saveState === "error" ? "Text save failed" : dirty ? "Unsaved text changes" : "Text changes saved"}</span>
                </div>
              ) : activePanel === "Effects" ? (
                <div className="editor-effects-panel">
                  {!selected ? <p className="editor-empty-copy">Select a video or overlay clip to edit its effects.</p> : (
                    <>
                      <div className="editor-effect-selection">
                        <strong>{selected.clip.label ?? selectedMedia?.name ?? "Selected clip"}</strong>
                        <Badge>{selected.track.name}</Badge>
                      </div>
                      {!["video", "overlay"].includes(selected.track.type) ? (
                        <p className="editor-hint">Visual effects can be applied to video and overlay clips.</p>
                      ) : (
                        <>
                          <Field label="Available effect">
                            <SelectInput
                              aria-label="Available effect"
                              disabled={selected.track.locked || (selected.clip.effects?.length ?? 0) >= 20}
                              onChange={(event) => setNewEffectType(event.target.value as TimelineEffectType)}
                              value={newEffectType}
                            >
                              {Object.entries(effectLimits).map(([type, config]) => (
                                <option key={type} value={type}>{config.label}</option>
                              ))}
                            </SelectInput>
                          </Field>
                          <Button disabled={selected.track.locked || (selected.clip.effects?.length ?? 0) >= 20} onClick={addSelectedEffect} size="sm"><Plus size={13} /> Add effect</Button>
                          <div className="editor-effect-list">
                            {(selected.clip.effects ?? []).map((effect, index) => {
                              const config = effectLimits[effect.type];
                              return (
                                <div className="editor-effect-row" key={effect.id}>
                                  <div className="editor-effect-row-heading">
                                    <label><input
                                      aria-label={`Enable ${config.label} effect ${index + 1}`}
                                      checked={effect.enabled}
                                      disabled={selected.track.locked}
                                      onChange={(event) => patchSelectedEffect(effect.id, { enabled: event.target.checked })}
                                      type="checkbox"
                                    />{config.label}</label>
                                    <div>
                                      <button
                                        aria-label={`Reset ${config.label} effect ${index + 1}`}
                                        disabled={selected.track.locked}
                                        onClick={() => patchSelectedEffect(effect.id, { value: config.initial })}
                                        type="button"
                                      >Reset</button>
                                      <button
                                        aria-label={`Remove ${config.label} effect ${index + 1}`}
                                        disabled={selected.track.locked}
                                        onClick={() => removeSelectedEffect(effect.id)}
                                        type="button"
                                      >Remove</button>
                                    </div>
                                  </div>
                                  <Field label={`${config.label} value`}>
                                    <TextInput
                                      aria-label={`${config.label} effect ${index + 1} value`}
                                      defaultValue={effect.value}
                                      disabled={selected.track.locked || !effect.enabled}
                                      key={`${effect.id}-${effect.value}-${effect.enabled}`}
                                      max={config.max}
                                      min={config.min}
                                      onBlur={(event) => {
                                        const parsed = Number(event.target.value);
                                        const value = Number.isFinite(parsed)
                                          ? Math.max(config.min, Math.min(config.max, parsed))
                                          : config.initial;
                                        patchSelectedEffect(effect.id, { value });
                                      }}
                                      step={config.step}
                                      type="number"
                                    />
                                  </Field>
                                </div>
                              );
                            })}
                            {(selected.clip.effects?.length ?? 0) > 0 && (
                              <Button
                                disabled={selected.track.locked}
                                onClick={() => patchSelected({ effects: [] })}
                                size="sm"
                              >Reset all effects</Button>
                            )}
                            {(selected.clip.effects?.length ?? 0) === 0 && <p className="editor-empty-copy">No effects on this clip.</p>}
                          </div>
                          <p className="editor-hint">Effect order is top to bottom. Changes are saved with the timeline.</p>
                        </>
                      )}
                    </>
                  )}
                  <span className={`save-indicator save-${saveState}`} role="status">{saveState === "saving" ? "Saving effects…" : saveState === "error" ? "Effect save failed" : dirty ? "Unsaved effect changes" : "Effects saved"}</span>
                  {error && <p className="editor-inline-error" role="alert">{error}</p>}
                </div>
              ) : activePanel === "Transitions" ? (
                <div className="editor-effects-panel">
                  {!selected ? <p className="editor-empty-copy">Select a video clip to edit its transitions.</p> : (
                    <>
                      <div className="editor-effect-selection">
                        <strong>{selected.clip.label ?? selectedMedia?.name ?? "Selected clip"}</strong>
                        <Badge>{selected.track.name}</Badge>
                      </div>
                      {selected.track.type !== "video" ? (
                        <p className="editor-hint">Video transitions are available on video-track clips.</p>
                      ) : (
                        <>
                          <Field label="Transition in">
                            <SelectInput
                              aria-label="Transition in"
                              disabled={selected.track.locked}
                              onChange={(event) => {
                                const transition = event.target.value as TimelineClip["transition_in"];
                                patchSelected({
                                  transition_in: transition,
                                  ...(transition === "cross_dissolve" ? { transition_in_version: 1 as const } : {}),
                                  ...(transition === "cross_dissolve"
                                    ? { transition_in_duration: Math.min(
                                      selected.clip.transition_in_duration ?? 0.5,
                                      selectedCrossDissolveOverlap,
                                    ) }
                                    : {}),
                                });
                              }}
                              value={selected.clip.transition_in ?? "none"}
                            >
                              <option value="none">None</option>
                              <option value="fade">Fade from black</option>
                              <option
                                disabled={selectedCrossDissolveOverlap < 0.05}
                                value="cross_dissolve"
                              >Cross dissolve</option>
                            </SelectInput>
                          </Field>
                          <Field label="Transition out">
                            <SelectInput
                              aria-label="Transition out"
                              disabled={selected.track.locked}
                              onChange={(event) => patchSelected({ transition_out: event.target.value as TimelineClip["transition_out"] })}
                              value={selected.clip.transition_out ?? "none"}
                            >
                              <option value="none">None</option>
                              <option value="fade">Fade to black</option>
                            </SelectInput>
                          </Field>
                          <Field label="Transition in duration (sec)">
                            <TextInput
                              aria-label="Transition in duration"
                              defaultValue={(selected.clip.transition_in_duration ?? 0.5).toFixed(2)}
                              disabled={selected.track.locked || selected.clip.transition_in === "none"}
                              key={`${selectedClip}-transition-in-duration-${selected.clip.transition_in_duration}`}
                              max={selected.clip.transition_in === "cross_dissolve"
                                ? Math.max(0.05, selectedCrossDissolveOverlap)
                                : selected.clip.duration}
                              min="0.05"
                              onBlur={(event) => {
                                const parsed = Number(event.target.value);
                                const value = Number.isFinite(parsed) ? Math.max(0.05, parsed) : 0.5;
                                patchSelected({ transition_in_duration: Math.min(
                                  value,
                                  selected.clip.transition_in === "cross_dissolve"
                                    ? Math.max(0.05, selectedCrossDissolveOverlap)
                                    : selected.clip.duration,
                                ) });
                              }}
                              step="0.05"
                              type="number"
                            />
                          </Field>
                          <Field label="Transition out duration (sec)">
                            <TextInput
                              aria-label="Transition out duration"
                              defaultValue={(selected.clip.transition_out_duration ?? 0.5).toFixed(2)}
                              disabled={selected.track.locked || selected.clip.transition_out === "none"}
                              key={`${selectedClip}-transition-out-duration-${selected.clip.transition_out_duration}`}
                              max={selected.clip.duration}
                              min="0.05"
                              onBlur={(event) => {
                                const parsed = Number(event.target.value);
                                patchSelected({ transition_out_duration: Math.min(
                                  selected.clip.duration,
                                  Math.max(0.05, Number.isFinite(parsed) ? parsed : 0.5),
                                ) });
                              }}
                              step="0.05"
                              type="number"
                            />
                          </Field>
                          <p className="editor-hint">Cross dissolve requires an overlapping preceding clip on this video track. Adjust clip positions to create the handle.</p>
                        </>
                      )}
                    </>
                  )}
                  <span className={`save-indicator save-${saveState}`} role="status">{saveState === "saving" ? "Saving transition…" : saveState === "error" ? "Transition save failed" : dirty ? "Unsaved transition changes" : "Transitions saved"}</span>
                  {error && <p className="editor-inline-error" role="alert">{error}</p>}
                </div>
              ) : (
                <div className="editor-asset-list">
                  {assets.filter((asset) => activePanel === "Audio" ? asset.media_type === "audio" : activePanel === "Assets" || asset.media_type !== "audio").map((asset) => {
                    const job = mediaJobs[asset.id];
                    const probe = asset.metadata_json?.probe;
                    const isProcessing = job?.status === "queued" || job?.status === "processing";
                    const technicalDetails = probe
                      ? [
                        probe.width && probe.height ? `${probe.width}×${probe.height}` : null,
                        probe.frame_rate ? `${probe.frame_rate.toFixed(1)} fps` : null,
                        probe.video_codec ?? probe.audio_streams?.[0]?.codec ?? null,
                      ].filter(Boolean).join(" · ")
                      : `${asset.media_type} · metadata pending`;
                    return (
                      <div className="editor-asset-card" key={asset.id}>
                        <button
                          aria-label={`Add ${asset.name} to the timeline and preview`}
                          className="editor-asset"
                          onClick={() => addAsset(asset)}
                          type="button"
                        >
                          <span className="editor-asset-icon">{asset.media_type === "audio" ? <AudioLines size={16} /> : asset.media_type === "image" ? <FileImage size={16} /> : <FileVideo2 size={16} />}</span>
                          <AssetThumbnail asset={asset} baseUrl={baseUrl} token={token} />
                          <span className="editor-asset-name">
                            <strong>{asset.name}</strong>
                            <small>{asset.duration_seconds ? `${asset.duration_seconds.toFixed(1)} sec` : "duration unknown"} · {technicalDetails}</small>
                          </span>
                          <Plus size={14} />
                        </button>
                        <div className="editor-asset-actions">
                          <span className={`editor-media-status status-${job?.status ?? (probe ? "completed" : "queued")}`}>
                            {job?.status ?? (probe ? "ready" : "queued")}
                            {isProcessing && ` · ${job.progress}%`}
                          </span>
                          <Button
                            aria-label={`Download ${asset.name}`}
                            onClick={() => void downloadMedia(baseUrl, token, asset.id).catch((downloadError) => setError(responseMessage(downloadError)))}
                            size="sm"
                          >
                            <Download size={13} />
                          </Button>
                        </div>
                        {isProcessing && <progress aria-label={`Processing ${asset.name}`} max={100} value={job.progress} />}
                        {job?.cancellation_requested && <small className="editor-media-job-note">Cancellation requested…</small>}
                        {(job?.status === "failed" || job?.status === "cancelled") && (
                          <div className="editor-media-job-error">
                            <small>{job.error_message ?? "Media processing did not complete."}</small>
                            {job.retry_count < job.max_retries && (
                              <Button onClick={() => void manageMediaJob(asset, "retry")} size="sm">Retry processing</Button>
                            )}
                          </div>
                        )}
                        {isProcessing && <Button onClick={() => void manageMediaJob(asset, "cancel")} size="sm">Cancel processing</Button>}
                      </div>
                    );
                  })}
                  {assets.length === 0 && <p className="editor-empty-copy">No media uploaded yet.</p>}
                </div>
              )}
              <div className="editor-import">
                <input accept="video/*,audio/*,image/*" aria-label="Select media file" className="visually-hidden" onChange={(event) => void importFile(event.target.files?.[0])} ref={fileInputRef} type="file" />
                <Button disabled={uploading} onClick={() => fileInputRef.current?.click()} size="sm"><Upload size={14} /> {uploading ? "Uploading…" : "Import media"}</Button>
                {uploading && <><progress aria-label="Upload progress" max={100} value={uploadProgress} /><small>Uploading · {uploadProgress}%</small></>}
              </div>
            </Card>
            <div className="editor-preview-column">
              <Card className="editor-preview-panel">
                <div className="editor-preview-header"><span><strong>Preview</strong><small>{activePreviewAsset?.name ?? "No visible clip at playhead"}</small></span><Badge>Composite timeline</Badge></div>
                <div className="editor-preview-canvas">
                  {loadedProjectId === projectId && projectId ? (
                    <TimelineCompositePreview
                      key={projectId}
                      ref={previewRef}
                      assets={assets}
                      baseUrl={baseUrl}
                      playhead={playhead}
                      playing={playing}
                      projectId={projectId}
                      seekRevision={seekRevision}
                      timeline={timeline}
                      token={token}
                    />
                  ) : <div className="editor-preview-placeholder">Loading project preview…</div>}
                </div>
                <div className="editor-transport">
                  <Button aria-label={playing ? "Pause timeline" : "Play timeline"} onClick={togglePlayback} size="sm">{playing ? <Pause size={15} /> : <Play size={15} />}</Button>
                  <span className="editor-timecode">{formatTime(playhead)} / {formatTime(timelineDuration)}</span>
                  <input aria-label="Timeline playhead" disabled={!timelineDuration} max={timelineDuration} min="0" onChange={(event) => seekTo(Number(event.target.value))} step={1 / timeline.frame_rate} type="range" value={Math.min(playhead, timelineDuration)} />
                  <Button aria-label="Split selected clip at playhead" disabled={!selected || selected.track.locked} onClick={splitSelected} size="sm"><Scissors size={15} /></Button>
                </div>
              </Card>
              <Card className="editor-timeline-panel">
                <div className="editor-timeline-toolbar">
                  <span><strong>Timeline</strong><small>{timeline.name} · {timeline.frame_rate} fps · {timeline.width}×{timeline.height}</small></span>
                  <div className="editor-timeline-tools">
                    <Button disabled={!selected || selected.track.locked} onClick={removeSelected} size="sm"><Trash2 size={14} /> Delete</Button>
                    <Button disabled={!selected || selected.track.locked} onClick={duplicateSelected} size="sm"><Copy size={14} /> Duplicate</Button>
                    <Button onClick={() => addTrack("video")} size="sm"><Plus size={14} /> Track</Button>
                    <label className="editor-zoom">Zoom <input aria-label="Timeline zoom" max="120" min="24" onChange={(event) => setZoom(Number(event.target.value))} type="range" value={zoom} /></label>
                  </div>
                </div>
                {loadedProjectId !== projectId ? <div className="editor-loading">Loading saved timeline…</div> : (
                  <div className="editor-timeline-scroll">
                    <div className="editor-timeline-ruler" style={{ minWidth: `${Math.max(900, (rulerDuration + 3) * zoom)}px` }}>
                      <div className="editor-track-controls-spacer" />
                      <div className="editor-ruler" onClick={(event) => {
                        const rect = event.currentTarget.getBoundingClientRect();
                        seekTo((event.clientX - rect.left) / zoom);
                      }}>
                        {Array.from({ length: Math.ceil(rulerDuration / 5) + 1 }, (_, index) => (
                          <span key={index} style={{ left: `${index * 5 * zoom}px` }}>{formatTime(index * 5).slice(0, 5)}</span>
                        ))}
                        <i className="editor-playhead" style={{ left: `${playhead * zoom}px` }} />
                      </div>
                    </div>
                    {timeline.tracks.map((track) => (
                      <div className="editor-track-row" data-editor-track-id={track.id} key={track.id} style={{ minWidth: `${Math.max(900, (rulerDuration + 3) * zoom)}px` }}>
                        <div className="editor-track-controls">
                          <strong>{track.name}</strong>
                          <span>{track.type}</span>
                          <button aria-label={`Move ${track.name} up`} disabled={timeline.tracks[0]?.id === track.id} onClick={() => moveTrack(track.id, -1)} type="button"><ChevronUp size={13} /></button>
                          <button aria-label={`Move ${track.name} down`} disabled={timeline.tracks.at(-1)?.id === track.id} onClick={() => moveTrack(track.id, 1)} type="button"><ChevronDown size={13} /></button>
                          <button aria-label={`${track.muted ? "Unmute" : "Mute"} ${track.name}`} onClick={() => toggleTrack(track.id, "muted")} type="button">{track.muted ? <VolumeX size={13} /> : <Volume2 size={13} />}</button>
                          <button aria-label={`${track.locked ? "Unlock" : "Lock"} ${track.name}`} onClick={() => toggleTrack(track.id, "locked")} type="button">{track.locked ? <Lock size={13} /> : <LockKeyholeOpen size={13} />}</button>
                          <button aria-label={`Add ${track.type} track`} onClick={() => addTrack(track.type)} type="button"><Plus size={13} /></button>
                          {track.type === "audio" && (
                            <input
                              aria-label={`${track.name} track volume`}
                              className="editor-track-volume"
                              disabled={track.locked}
                              max="2"
                              min="0"
                              onChange={(event) => setTrackVolume(track.id, Number(event.target.value))}
                              step="0.05"
                              title={`Track volume: ${track.volume.toFixed(2)}`}
                              type="range"
                              value={track.volume}
                            />
                          )}
                        </div>
                        <div className="editor-track-lane" onClick={(event) => {
                          const rect = event.currentTarget.getBoundingClientRect();
                          seekTo((event.clientX - rect.left) / zoom);
                        }}>
                          {track.clips.map((clip) => (
                            <button
                              aria-label={`${clip.label ?? assetById.get(clip.media_asset_id ?? "")?.name ?? "Text clip"} on ${track.name}, starts at ${clip.start.toFixed(2)} seconds, duration ${clip.duration.toFixed(2)} seconds`}
                              aria-pressed={selectedClip === clip.id}
                              className={`editor-timeline-clip clip-${track.type}${selectedClip === clip.id ? " selected" : ""}`}
                              key={clip.id}
                              title={`${track.name} · ${clip.start.toFixed(2)}–${(clip.start + clip.duration).toFixed(2)} sec · ${clip.duration.toFixed(2)} sec`}
                              onClick={(event) => { event.stopPropagation(); setSelectedClip(clip.id); seekTo(clip.start); }}
                              onPointerDown={(event) => startDrag(event, track, clip)}
                              onPointerMove={moveDrag}
                              onPointerUp={finishDrag}
                              onPointerCancel={finishDrag}
                              onKeyDown={(event) => {
                                if (event.key === "Enter" || event.key === " ") setSelectedClip(clip.id);
                              }}
                              style={{ left: `${clip.start * zoom}px`, width: `${Math.max(2, clip.duration * zoom)}px` }}
                              type="button"
                            >
                              <span>{clip.label ?? assetById.get(clip.media_asset_id ?? "")?.name ?? clip.text ?? "Clip"}</span>
                              {track.type === "audio" && (
                                <AudioWaveform
                                  asset={assetById.get(clip.media_asset_id ?? "")}
                                  baseUrl={baseUrl}
                                  token={token}
                                />
                              )}
                            </button>
                          ))}
                          <i className="editor-playhead" style={{ left: `${playhead * zoom}px` }} />
                        </div>
                      </div>
                    ))}
                    <div className="editor-add-track-row">
                      <button onClick={() => addTrack("video")} type="button"><Plus size={13} /> Video</button>
                      <button onClick={() => addTrack("audio")} type="button"><Plus size={13} /> Audio</button>
                      <button onClick={() => addTrack("overlay")} type="button"><Plus size={13} /> Overlay</button>
                      <button onClick={() => addTrack("subtitle")} type="button"><Plus size={13} /> Subtitles</button>
                    </div>
                  </div>
                )}
              </Card>
            </div>
            <Card className="editor-inspector">
              <div className="editor-inspector-heading"><strong>Properties</strong><ChevronDown size={14} /></div>
              {selected ? (
                <>
                  <div className="editor-inspector-asset">{selectedMedia?.name ?? selected.clip.text ?? "Text clip"}<Badge>{selected.track.type}</Badge></div>
                  {selected.track.locked && <p className="editor-hint">This track is locked. Unlock it to move or edit its clips.</p>}
                  <Field label="Timeline position (sec)"><TextInput defaultValue={selected.clip.start.toFixed(2)} disabled={selected.track.locked} key={`${selectedClip}-start-${selected.clip.start}`} min="0" onBlur={(event) => patchSelected({ start: Math.max(0, Number(event.target.value) || 0) })} type="number" /></Field>
                  <Field label="Duration (sec)"><TextInput defaultValue={selected.clip.duration.toFixed(2)} disabled={selected.track.locked} key={`${selectedClip}-duration-${selected.clip.duration}`} min="0.05" onBlur={(event) => patchSelected({ duration: Math.max(0.05, Number(event.target.value) || 0.05) })} step="0.05" type="number" /></Field>
                  <Field label="Source in (sec)"><TextInput defaultValue={selected.clip.source_start.toFixed(2)} disabled={selected.track.locked} key={`${selectedClip}-source-${selected.clip.source_start}`} min="0" onBlur={(event) => patchSelected({ source_start: Math.max(0, Number(event.target.value) || 0) })} step="0.05" type="number" /></Field>
                  {selected.track.type === "video" && <div className="editor-trim-actions"><Button disabled={selected.track.locked || playhead <= selected.clip.start || playhead >= selected.clip.start + selected.clip.duration} onClick={trimStartToPlayhead} size="sm">Trim start</Button><Button disabled={selected.track.locked || playhead <= selected.clip.start || playhead >= selected.clip.start + selected.clip.duration} onClick={trimEndToPlayhead} size="sm">Trim end</Button></div>}
                  {selected.track.type !== "subtitle" && (
                    <>
                      <Field label="Clip volume"><TextInput defaultValue={(selected.clip.volume ?? 1).toFixed(2)} disabled={selected.track.locked} key={`${selectedClip}-volume-${selected.clip.volume}`} max="2" min="0" onBlur={(event) => patchSelected({ volume: Math.max(0, Math.min(2, Number(event.target.value) || 0)) })} step="0.05" type="number" /></Field>
                      <Field label="Opacity"><TextInput defaultValue={(selected.clip.opacity ?? 1).toFixed(2)} disabled={selected.track.locked} key={`${selectedClip}-opacity-${selected.clip.opacity}`} max="1" min="0" onBlur={(event) => patchSelected({ opacity: Math.max(0, Math.min(1, Number(event.target.value) || 0)) })} step="0.05" type="number" /></Field>
                      {selected.track.type !== "audio" && (
                        <>
                          <Field label="Scale"><TextInput defaultValue={(selected.clip.scale ?? 1).toFixed(2)} disabled={selected.track.locked} key={`${selectedClip}-scale-${selected.clip.scale}`} max="4" min="0.05" onBlur={(event) => patchSelected({ scale: Math.max(0.05, Math.min(4, Number(event.target.value) || 0.05)) })} step="0.05" type="number" /></Field>
                          <Field label="Position X"><TextInput defaultValue={(selected.clip.position_x ?? 0.5).toFixed(2)} disabled={selected.track.locked} key={`${selectedClip}-x-${selected.clip.position_x}`} max="1" min="0" onBlur={(event) => patchSelected({ position_x: Math.max(0, Math.min(1, Number(event.target.value) || 0)) })} step="0.05" type="number" /></Field>
                          <Field label="Position Y"><TextInput defaultValue={(selected.clip.position_y ?? 0.5).toFixed(2)} disabled={selected.track.locked} key={`${selectedClip}-y-${selected.clip.position_y}`} max="1" min="0" onBlur={(event) => patchSelected({ position_y: Math.max(0, Math.min(1, Number(event.target.value) || 0)) })} step="0.05" type="number" /></Field>
                          <Field label="Brightness"><TextInput defaultValue={(selected.clip.brightness ?? 0).toFixed(2)} disabled={selected.track.locked} key={`${selectedClip}-brightness-${selected.clip.brightness}`} max="1" min="-1" onBlur={(event) => patchSelected({ brightness: Math.max(-1, Math.min(1, Number(event.target.value) || 0)) })} step="0.05" type="number" /></Field>
                          <Field label="Contrast"><TextInput defaultValue={(selected.clip.contrast ?? 1).toFixed(2)} disabled={selected.track.locked} key={`${selectedClip}-contrast-${selected.clip.contrast}`} max="3" min="0" onBlur={(event) => patchSelected({ contrast: Math.max(0, Math.min(3, Number(event.target.value) || 0)) })} step="0.05" type="number" /></Field>
                          <Field label="Saturation"><TextInput defaultValue={(selected.clip.saturation ?? 1).toFixed(2)} disabled={selected.track.locked} key={`${selectedClip}-saturation-${selected.clip.saturation}`} max="3" min="0" onBlur={(event) => patchSelected({ saturation: Math.max(0, Math.min(3, Number(event.target.value) || 0)) })} step="0.05" type="number" /></Field>
                        </>
                      )}
                      <Field label="Fade in (sec)"><TextInput defaultValue={(selected.clip.fade_in ?? 0).toFixed(2)} disabled={selected.track.locked} key={`${selectedClip}-fade-in-${selected.clip.fade_in}`} min="0" onBlur={(event) => patchSelected({ fade_in: Math.min(selected.clip.duration, Math.max(0, Number(event.target.value) || 0)) })} step="0.05" type="number" /></Field>
                      <Field label="Fade out (sec)"><TextInput defaultValue={(selected.clip.fade_out ?? 0).toFixed(2)} disabled={selected.track.locked} key={`${selectedClip}-fade-out-${selected.clip.fade_out}`} min="0" onBlur={(event) => patchSelected({ fade_out: Math.min(selected.clip.duration, Math.max(0, Number(event.target.value) || 0)) })} step="0.05" type="number" /></Field>
                    </>
                  )}
                  {selected.track.type === "subtitle" && <p className="editor-hint">Subtitle clips are burned into the rendered video.</p>}
                  <div className="editor-keyframes">
                    <Field label="Keyframe property">
                      <SelectInput value={keyframeProperty} onChange={(event) => setKeyframeProperty(event.target.value as typeof keyframeProperty)}>
                        <option value="opacity">Opacity</option><option value="scale">Scale</option><option value="x">Position X</option><option value="y">Position Y</option><option value="volume">Volume</option>
                      </SelectInput>
                    </Field>
                    <Field label="Keyframe value"><TextInput max={keyframeProperty === "opacity" || keyframeProperty === "x" || keyframeProperty === "y" ? "1" : keyframeProperty === "scale" ? "4" : "2"} min={keyframeProperty === "scale" ? "0.05" : "0"} onChange={(event) => setKeyframeValue(Number(event.target.value))} step="0.05" type="number" value={keyframeValue} /></Field>
                    <Button disabled={selected.track.locked} onClick={addSelectedKeyframe} size="sm">Add keyframe at playhead</Button>
                    <small>{selected.clip.keyframes?.length ?? 0} keyframes · linear interpolation</small>
                  </div>
                </>
              ) : <p className="editor-empty-copy">Select a clip to edit its position, duration, and source in point.</p>}
              <div className="editor-export-note">
                <strong>Export scope</strong>
                <p>MP4 export renders the full ordered timeline with gaps, visible video/image overlays, text, and mixed audio tracks. Presets require every video source to meet the selected long-edge resolution.</p>
                {exportMessage && <span>{exportMessage}</span>}
                {exporting && <progress aria-label="Export progress" max={100} value={exportProgress} />}
              </div>
            </Card>
          </div>
          {error && <div className="editor-inline-error" role="alert">{error}<button onClick={() => setError("")} type="button">Dismiss</button></div>}
        </>
      )}
      {projectDialogOpen && (
        <Dialog
          description="Create a project to hold your timeline and media edits."
          onClose={() => setProjectDialogOpen(false)}
          title="New project"
        >
          <form className="editor-dialog-form" onSubmit={(event) => {
            event.preventDefault();
            void makeProject(projectName);
          }}>
            <Field label="Project name"><TextInput autoFocus maxLength={160} onChange={(event) => setProjectName(event.target.value)} required value={projectName} /></Field>
            <Button disabled={!projectName.trim()} type="submit" variant="primary">Create project</Button>
          </form>
        </Dialog>
      )}
      {subtitleDialogOpen && (
        <Dialog
          description="Add a text cue to the subtitle track. Text is burned into exports."
          onClose={() => setSubtitleDialogOpen(false)}
          title="Add subtitle"
        >
          <form className="editor-dialog-form" onSubmit={(event) => {
            event.preventDefault();
            addSubtitleClip(subtitleText);
            setSubtitleText("");
            setSubtitleDialogOpen(false);
          }}>
            <Field label="Subtitle text"><TextInput autoFocus maxLength={10_000} onChange={(event) => setSubtitleText(event.target.value)} required value={subtitleText} /></Field>
            <Button disabled={!subtitleText.trim()} type="submit" variant="primary">Add to timeline</Button>
          </form>
        </Dialog>
      )}
    </div>
  );
}
