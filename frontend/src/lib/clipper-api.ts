export type ClipCandidate = {
  id: string;
  project_id: string;
  source_asset_id: string | null;
  title: string | null;
  start_seconds: number;
  end_seconds: number;
  score: number | null;
  scoring_factors: Record<string, number> | null;
  scene_ranges: Array<{ scene_index: number; start_seconds: number; end_seconds: number }> | null;
  explanation: string | null;
  status: "candidate" | "approved" | "rejected";
  transcript_text: string | null;
  caption_data: ClipCaption[] | null;
  framing_data: { aspect_ratio?: string; position_x?: number; position_y?: number } | null;
  exported_media_asset_id: string | null;
  created_at: string;
};

export type ClipCaption = {
  start_seconds: number;
  end_seconds: number;
  text: string;
  speaker_label?: string | null;
  highlighted_words: string[];
};

export type ClipJob = {
  id: string;
  project_id: string | null;
  job_type: "smart_clip_analysis" | "smart_clip_export";
  status: "queued" | "processing" | "completed" | "failed" | "cancelled";
  progress: number;
  input_data: Record<string, unknown> | null;
  output_data: Record<string, unknown> | null;
  error_message: string | null;
  retry_count: number;
  max_retries: number;
  created_at: string;
  updated_at: string;
};

export type ClipAnalysisInput = {
  project_id: string;
  source_media_asset_id: string;
  minimum_duration_seconds: number;
  maximum_duration_seconds: number;
  target_durations_seconds?: Array<15 | 30 | 45 | 60>;
};

export type ClipRankPreferences = Record<
  | "scene_changes"
  | "speech_activity"
  | "silence_boundaries"
  | "sentence_completeness"
  | "beginning_quality"
  | "ending_quality"
  | "interesting_opening"
  | "question_or_answer"
  | "key_insight"
  | "emotional_language"
  | "standalone_thought"
  | "pacing",
  number
>;

export type ClipExportInput = {
  candidate_ids: string[];
  aspect_ratio: "9:16" | "1:1" | "4:5" | "16:9";
  resolution: "720p" | "1080p";
  captions: boolean;
  caption_position: "top" | "center" | "bottom";
  caption_theme: "boxed" | "outline" | "minimal";
  caption_font_size: number;
  caption_color: string;
  caption_background_color: string;
  caption_outline_color: string;
  animated_highlighting: boolean;
  watermark?: string;
};

type APIErrorResponse = { error?: { message?: string }; detail?: string };

function endpoint(baseUrl: string, path: string) {
  return `${baseUrl.replace(/\/+$/, "")}/api/v1${path}`;
}

async function request<T>(
  baseUrl: string,
  token: string,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init?.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(endpoint(baseUrl, path), { ...init, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as APIErrorResponse;
    throw new Error(body.error?.message ?? body.detail ?? `Smart Clipper request failed (${response.status}).`);
  }
  if (response.status === 204) return undefined as T;
  return await response.json() as T;
}

export function createClipAnalysis(baseUrl: string, token: string, input: ClipAnalysisInput) {
  return request<ClipJob>(baseUrl, token, "/clipper/analyses", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getClipJob(baseUrl: string, token: string, jobId: string) {
  return request<ClipJob>(baseUrl, token, `/clipper/jobs/${jobId}`);
}

export function listClipCandidates(baseUrl: string, token: string, projectId: string) {
  return request<ClipCandidate[]>(baseUrl, token, `/clipper/projects/${projectId}/candidates`);
}

export function getClipperCapabilities(baseUrl: string, token: string) {
  return request<{
    scene_detection: { available: boolean; provider: string };
    silence_detection: { available: boolean; provider: string | null };
    speaker_diarization: { available: boolean; provider: string | null; note: string };
    transcription: {
      available: boolean;
      provider: string | null;
      timestamp_precision: "segment";
      word_timestamps_available: boolean;
    };
    rendering: { available: boolean; provider: string | null };
    subtitle_export: { available: boolean; format: string };
    face_tracking: { available: boolean; provider: string | null; fallback: string };
  }>(baseUrl, token, "/clipper/capabilities");
}

export function rankClipCandidates(
  baseUrl: string,
  token: string,
  projectId: string,
  preferences: ClipRankPreferences,
) {
  return request<ClipCandidate[]>(baseUrl, token, `/clipper/projects/${projectId}/ranking`, {
    method: "PATCH",
    body: JSON.stringify({ preferences }),
  });
}

export function updateClipCandidate(
  baseUrl: string,
  token: string,
  candidateId: string,
  input: { start_seconds: number; end_seconds: number },
) {
  return request<ClipCandidate>(baseUrl, token, `/clipper/candidates/${candidateId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function setClipCandidateStatus(
  baseUrl: string,
  token: string,
  candidateId: string,
  status: "approve" | "reject",
) {
  return request<ClipCandidate>(baseUrl, token, `/clipper/candidates/${candidateId}/${status}`, {
    method: "POST",
  });
}

export function updateClipCaptions(
  baseUrl: string,
  token: string,
  candidateId: string,
  captions: ClipCaption[],
) {
  return request<ClipCandidate>(baseUrl, token, `/clipper/candidates/${candidateId}/captions`, {
    method: "PATCH",
    body: JSON.stringify({ captions }),
  });
}

export function updateClipFraming(
  baseUrl: string,
  token: string,
  candidateId: string,
  framing: { aspect_ratio: string; position_x: number; position_y: number },
) {
  return request<ClipCandidate>(baseUrl, token, `/clipper/candidates/${candidateId}/framing`, {
    method: "PATCH",
    body: JSON.stringify(framing),
  });
}

export function createClipExport(baseUrl: string, token: string, input: ClipExportInput) {
  return request<ClipJob>(baseUrl, token, "/clipper/exports", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function retryClipJob(baseUrl: string, token: string, jobId: string) {
  return request<ClipJob>(baseUrl, token, `/clipper/jobs/${jobId}/retry`, { method: "POST" });
}

export function cancelClipJob(baseUrl: string, token: string, jobId: string) {
  return request<ClipJob>(baseUrl, token, `/clipper/jobs/${jobId}/cancel`, { method: "POST" });
}

export async function downloadClipJobAsset(baseUrl: string, token: string, assetId: string) {
  const response = await fetch(endpoint(baseUrl, `/media/${assetId}/download`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error(`Could not download exported clip (${response.status}).`);
  return await response.blob();
}

export async function downloadClipCaptions(
  baseUrl: string,
  token: string,
  candidateId: string,
  format: "srt" | "vtt",
) {
  const response = await fetch(
    endpoint(baseUrl, `/clipper/candidates/${candidateId}/captions?format=${format}`),
    { headers: { Authorization: `Bearer ${token}` } },
  );
  if (!response.ok) throw new Error(`Could not download captions (${response.status}).`);
  return await response.blob();
}
