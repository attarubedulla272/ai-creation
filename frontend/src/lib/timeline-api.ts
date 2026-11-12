import type { MediaAsset } from "@/lib/media-api";

export type TimelineTrackType = "video" | "overlay" | "audio" | "subtitle";

export type TimelineEffectType = "brightness" | "contrast" | "saturation" | "grayscale" | "blur";
export type TimelineEffect = {
  id: string;
  type: TimelineEffectType;
  enabled: boolean;
  value: number;
};

export type TimelineTextStyle = {
  font_family: "sans-serif" | "serif" | "monospace";
  font_size: number;
  font_weight: "normal" | "bold";
  font_style: "normal" | "italic";
  color: string;
  background_color: string;
  background_opacity: number;
  outline_color: string;
  outline_width: number;
  shadow_color: string;
  shadow_blur: number;
  alignment: "left" | "center" | "right";
  vertical_alignment: "top" | "middle" | "bottom";
  width: number;
};

export const DEFAULT_TIMELINE_TEXT_STYLE: TimelineTextStyle = {
  font_family: "sans-serif",
  font_size: 48,
  font_weight: "bold",
  font_style: "normal",
  color: "#FFFFFF",
  background_color: "#11111B",
  background_opacity: 0,
  outline_color: "#000000",
  outline_width: 2,
  shadow_color: "#000000",
  shadow_blur: 0,
  alignment: "center",
  vertical_alignment: "middle",
  width: 0.84,
};

export type SubtitleCue = {
  start: number;
  duration: number;
  text: string;
};

export type TimelineClip = {
  id: string;
  media_asset_id: string | null;
  start: number;
  duration: number;
  source_start: number;
  source_end: number | null;
  text?: string | null;
  text_style?: TimelineTextStyle;
  z_index?: number;
  label?: string | null;
  position_x?: number;
  position_y?: number;
  scale?: number;
  opacity?: number;
  volume?: number;
  fade_in?: number;
  fade_out?: number;
  transition_in?: "none" | "fade" | "cross_dissolve" | "wipe_left" | "wipe_right";
  transition_out?: "none" | "fade" | "cross_dissolve" | "wipe_left" | "wipe_right";
  transition_in_version?: 0 | 1;
  transition_in_duration?: number;
  transition_out_duration?: number;
  brightness?: number;
  contrast?: number;
  saturation?: number;
  effects?: TimelineEffect[];
  keyframes?: Array<{
    time: number;
    property: "x" | "y" | "scale" | "opacity" | "volume";
    value: number;
    interpolation: "linear" | "hold";
  }>;
};

export type TimelineTrack = {
  id: string;
  name: string;
  type: TimelineTrackType;
  muted: boolean;
  solo?: boolean;
  locked: boolean;
  volume: number;
  clips: TimelineClip[];
};

export type TimelineDocument = {
  version: 1;
  name: string;
  frame_rate: number;
  width: number;
  height: number;
  tracks: TimelineTrack[];
};

export type StudioProject = {
  id: string;
  name: string;
  description: string | null;
};

export type ExportStatus = {
  job_id?: string;
  id?: string;
  status: "queued" | "processing" | "completed" | "failed" | "cancelled";
  progress: number;
  error_message?: string | null;
  retry_count?: number;
  max_retries?: number;
  cancellation_requested?: boolean;
};

export type TimelineTextValidationIssue = {
  clip_id: string;
  track_name: string;
  severity: "error" | "warning";
  code: "font" | "layout" | "empty_text" | "subtitle_duration" | "unsupported_style";
  message: string;
  recommendation: string;
  alternatives: string[];
};

export type TimelineTextValidationResponse = {
  issues: TimelineTextValidationIssue[];
};

export type TimelineTextFitOperation = "fit_width" | "shrink" | "split";

export type TimelineTextFitResponse = {
  timeline: TimelineDocument;
  warnings: string[];
};

export const DEFAULT_BACKEND_URL = "http://localhost:8000";
export const MEDIA_TOKEN_KEY = "ai-creator-studio:media-token";
export const BACKEND_URL_KEY = "ai-creator-studio:backend-url";

function endpoint(baseUrl: string, path: string) {
  return `${baseUrl.replace(/\/+$/, "")}/api/v1${path}`;
}

async function request<T>(baseUrl: string, token: string, path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init?.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  let response: Response;
  try {
    response = await fetch(endpoint(baseUrl, path), { ...init, headers });
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(
        `Cannot reach the backend at ${baseUrl}. Start the FastAPI service there, or update the Backend URL; also check that CORS allows this frontend.`,
      );
    }
    throw error;
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as {
      error?: { message?: string };
      detail?: string | { message?: string };
    };
    const detail = typeof body.detail === "string" ? body.detail : body.detail?.message;
    throw new Error(body.error?.message ?? detail ?? `Backend request failed (${response.status}).`);
  }
  return await response.json() as T;
}

export function importSubtitleFile(
  baseUrl: string,
  token: string,
  projectId: string,
  file: File,
) {
  const form = new FormData();
  form.set("file", file);
  return request<SubtitleCue[]>(baseUrl, token, `/projects/${projectId}/timeline/subtitles/import`, {
    method: "POST",
    body: form,
  });
}

export async function downloadSubtitles(
  baseUrl: string,
  token: string,
  projectId: string,
  format: "srt" | "vtt",
) {
  const headers = new Headers();
  headers.set("Authorization", ["Bearer", token].join(" "));
  let response: Response;
  try {
    response = await fetch(
      endpoint(baseUrl, `/projects/${projectId}/timeline/subtitles/export?format=${format}`),
      { headers },
    );
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(
        `Cannot reach the backend at ${baseUrl}. Start the FastAPI service there, or update the Backend URL; also check that CORS allows this frontend.`,
      );
    }
    throw error;
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as {
      error?: { message?: string };
      detail?: string;
    };
    throw new Error(body.error?.message ?? body.detail ?? `Could not export subtitles (${response.status}).`);
  }
  return await response.blob();
}

export function listStudioProjects(baseUrl: string, token: string) {
  return request<StudioProject[]>(baseUrl, token, "/projects");
}

export function createStudioProject(baseUrl: string, token: string, name: string) {
  return request<StudioProject>(baseUrl, token, "/projects", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function listStudioMedia(baseUrl: string, token: string) {
  return request<MediaAsset[]>(baseUrl, token, "/media");
}

export function loadTimeline(baseUrl: string, token: string, projectId: string) {
  return request<{ id: string; project_id: string; timeline_data: TimelineDocument }>(
    baseUrl,
    token,
    `/projects/${projectId}/timeline`,
  );
}

export function saveTimeline(
  baseUrl: string,
  token: string,
  projectId: string,
  timeline: TimelineDocument,
) {
  return request<{ id: string; project_id: string; updated_at: string }>(
    baseUrl,
    token,
    `/projects/${projectId}/timeline`,
    { method: "PUT", body: JSON.stringify(timeline) },
  );
}

export function queueTimelineExport(
  baseUrl: string,
  token: string,
  projectId: string,
  selectedClipIds: string[] = [],
  preset: "720p" | "1080p" | "4k" | null = null,
) {
  return request<ExportStatus>(baseUrl, token, `/projects/${projectId}/timeline/export`, {
    method: "POST",
    body: JSON.stringify({ selected_clip_ids: selectedClipIds, preset }),
  });
}

export function validateTimelineText(
  baseUrl: string,
  token: string,
  projectId: string,
  timeline: TimelineDocument,
  preset: "720p" | "1080p" | "4k" | null,
) {
  return request<TimelineTextValidationResponse>(
    baseUrl,
    token,
    `/projects/${projectId}/timeline/text-validation`,
    { method: "POST", body: JSON.stringify({ timeline, preset }) },
  );
}

export function proposeTimelineTextFit(
  baseUrl: string,
  token: string,
  projectId: string,
  timeline: TimelineDocument,
  clipId: string,
  operation: TimelineTextFitOperation,
  preset: "720p" | "1080p" | "4k" | null,
  minimumFontSize: number,
) {
  return request<TimelineTextFitResponse>(
    baseUrl,
    token,
    `/projects/${projectId}/timeline/text-fit`,
    {
      method: "POST",
      body: JSON.stringify({
        timeline,
        clip_id: clipId,
        operation,
        preset,
        minimum_font_size: minimumFontSize,
      }),
    },
  );
}

export function getTimelineExport(baseUrl: string, token: string, jobId: string) {
  return request<ExportStatus>(baseUrl, token, `/timeline/exports/${jobId}`);
}

export function retryTimelineExport(baseUrl: string, token: string, jobId: string) {
  return request<ExportStatus>(baseUrl, token, `/timeline/exports/${jobId}/retry`, {
    method: "POST",
  });
}

export function cancelTimelineExport(baseUrl: string, token: string, jobId: string) {
  return request<ExportStatus>(baseUrl, token, `/timeline/exports/${jobId}/cancel`, {
    method: "POST",
  });
}

export async function downloadTimelineExport(baseUrl: string, token: string, jobId: string) {
  const response = await fetch(endpoint(baseUrl, `/timeline/exports/${jobId}/download`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error(`Could not download export (${response.status}).`);
  return await response.blob();
}

export async function loadMediaPreview(baseUrl: string, token: string, assetId: string) {
  const response = await fetch(endpoint(baseUrl, `/media/${assetId}/download`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error(`Could not preview media (${response.status}).`);
  return URL.createObjectURL(await response.blob());
}
