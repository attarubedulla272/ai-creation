export type VoiceProviderCapability = {
  available: boolean;
  provider: string | null;
  runs_locally: boolean | null;
  supported_languages?: string[];
  candidate_languages?: string[];
};

export type VoiceProviders = {
  transcription: VoiceProviderCapability;
  translation: VoiceProviderCapability;
  text_to_speech: VoiceProviderCapability;
  speaker_diarization: VoiceProviderCapability;
};

export type VoiceConsent = {
  id: string;
  authorization_basis: "self_attestation" | "authorized_person";
  consent_text_version: string;
  granted_at: string;
  revoked_at: string | null;
};

export type VoiceProfile = {
  id: string;
  name: string;
  language: string | null;
  status: string;
  reference_asset_id: string | null;
  consent_id: string;
  created_at: string;
};

export type VoiceJob = {
  id: string;
  job_type: string;
  status: "queued" | "processing" | "completed" | "failed" | "cancelled";
  progress: number;
  output_data: {
    transcript_id?: string;
    dubbing_project_id?: string;
    completed_segment_ids?: string[];
    media_asset_id?: string;
    video_asset_id?: string | null;
  } | null;
  error_message: string | null;
  retry_count: number;
  max_retries: number;
  created_at: string;
  updated_at: string;
};

export type TranscriptSegment = {
  id: string;
  order_index: number;
  start_seconds: number;
  end_seconds: number;
  text: string;
  speaker_label: string | null;
  translated_text: string | null;
  voice_profile_id: string | null;
  speech_rate: number;
};

export type VoiceTranscript = {
  id: string;
  project_id: string;
  media_asset_id: string | null;
  language: string | null;
  status: string;
  segments: TranscriptSegment[];
  created_at: string;
};

export type TranscriptRevision = {
  id: string;
  transcript_id: string;
  revision_number: number;
  snapshot: Array<{
    id: string;
    order_index: number;
    start_seconds: number;
    end_seconds: number;
    text: string;
    speaker_label: string | null;
    translated_text: string | null;
  }>;
  created_at: string;
};

export type DubbingGlossaryTerm = {
  source: string;
  translation: string;
  notes?: string;
};

export type DubbingSegment = {
  id: string;
  source_segment_id: string;
  order_index: number;
  start_seconds: number;
  end_seconds: number;
  source_text: string;
  translated_text: string;
  speaker_label: string | null;
  voice_profile_id: string | null;
  speech_rate: number;
  audio_asset_id: string | null;
  audio_source: "user_supplied" | null;
  original_start_seconds: number;
  original_end_seconds: number;
  audio_duration_seconds: number | null;
  translation_approved: boolean;
  translation_status: "not_translated" | "queued" | "completed" | "failed" | "cancelled" | "manual";
  translation_provider: string | null;
  translation_model: string | null;
  translation_model_version: string | null;
  translation_error: string | null;
  segment_approved: boolean;
  timing_conflict: boolean;
  processing_status: "not_generated" | "user_audio_attached";
  generated_audio_path: string | null;
};

export type DubbingProject = {
  id: string;
  project_id: string;
  transcript_id: string;
  target_language: string;
  status: string;
  segments_data: DubbingSegment[];
  glossary: DubbingGlossaryTerm[];
  created_at: string;
};

type APIErrorResponse = {
  error?: { message?: string };
  detail?: string;
};

function apiUrl(baseUrl: string, path: string) {
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
  const response = await fetch(apiUrl(baseUrl, path), { ...init, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as APIErrorResponse;
    throw new Error(body.error?.message ?? body.detail ?? `Voice Studio request failed (${response.status}).`);
  }
  if (response.status === 204) return undefined as T;
  return await response.json() as T;
}

export function getVoiceProviders(baseUrl: string, token: string) {
  return request<VoiceProviders>(baseUrl, token, "/voice/providers");
}

export function listVoiceConsents(baseUrl: string, token: string) {
  return request<VoiceConsent[]>(baseUrl, token, "/voice/consents");
}

export function createVoiceConsent(
  baseUrl: string,
  token: string,
  authorizationBasis: VoiceConsent["authorization_basis"],
) {
  return request<VoiceConsent>(baseUrl, token, "/voice/consents", {
    method: "POST",
    body: JSON.stringify({
      accepted: true,
      authorization_basis: authorizationBasis,
      consent_text_version: "voice-consent-v1",
    }),
  });
}

export function revokeVoiceConsent(baseUrl: string, token: string, consentId: string) {
  return request<VoiceConsent>(baseUrl, token, `/voice/consents/${consentId}/revoke`, {
    method: "POST",
  });
}

export function listVoiceProfiles(baseUrl: string, token: string) {
  return request<VoiceProfile[]>(baseUrl, token, "/voice/profiles");
}

export function createVoiceProfile(
  baseUrl: string,
  token: string,
  input: { name: string; language: string; consent_id: string; reference_asset_id: string },
) {
  return request<VoiceProfile>(baseUrl, token, "/voice/profiles", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function listVoiceTranscripts(baseUrl: string, token: string) {
  return request<VoiceTranscript[]>(baseUrl, token, "/voice/transcripts");
}

export function listTranscriptRevisions(baseUrl: string, token: string, transcriptId: string) {
  return request<TranscriptRevision[]>(
    baseUrl,
    token,
    `/voice/transcripts/${transcriptId}/revisions`,
  );
}

export function queueVoiceTranscription(
  baseUrl: string,
  token: string,
  input: { project_id: string; media_asset_id: string; language?: string },
) {
  return request<VoiceJob>(baseUrl, token, "/voice/transcriptions", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getVoiceJob(baseUrl: string, token: string, jobId: string) {
  return request<VoiceJob>(baseUrl, token, `/voice/jobs/${jobId}`);
}

export function cancelVoiceJob(baseUrl: string, token: string, jobId: string) {
  return request<VoiceJob>(baseUrl, token, `/voice/jobs/${jobId}/cancel`, { method: "POST" });
}

export function retryVoiceJob(baseUrl: string, token: string, jobId: string) {
  return request<VoiceJob>(baseUrl, token, `/voice/jobs/${jobId}/retry`, { method: "POST" });
}

export function queueDubbingTranslation(
  baseUrl: string,
  token: string,
  dubbingProjectId: string,
  regenerateExisting = false,
) {
  return request<VoiceJob>(baseUrl, token, `/voice/dubbing-projects/${dubbingProjectId}/translate`, {
    method: "POST",
    body: JSON.stringify({ regenerate_existing: regenerateExisting }),
  });
}

export function queueDubbingSegmentTranslation(
  baseUrl: string,
  token: string,
  dubbingProjectId: string,
  segmentId: string,
) {
  return request<VoiceJob>(
    baseUrl,
    token,
    `/voice/dubbing-projects/${dubbingProjectId}/segments/${segmentId}/translate`,
    { method: "POST" },
  );
}

export function updateTranscriptSegment(
  baseUrl: string,
  token: string,
  transcriptId: string,
  segmentId: string,
  patch: Pick<TranscriptSegment, "text" | "speaker_label" | "translated_text">,
) {
  return request<VoiceTranscript>(
    baseUrl,
    token,
    `/voice/transcripts/${transcriptId}/segments/${segmentId}`,
    { method: "PATCH", body: JSON.stringify(patch) },
  );
}

export function listDubbingProjects(baseUrl: string, token: string) {
  return request<DubbingProject[]>(baseUrl, token, "/voice/dubbing-projects");
}

export function createDubbingProject(
  baseUrl: string,
  token: string,
  transcriptId: string,
  targetLanguage: string,
) {
  return request<DubbingProject>(baseUrl, token, "/voice/dubbing-projects", {
    method: "POST",
    body: JSON.stringify({ transcript_id: transcriptId, target_language: targetLanguage }),
  });
}

export function updateDubbingProject(
  baseUrl: string,
  token: string,
  dubbingProjectId: string,
  segments: DubbingSegment[],
  glossary: DubbingGlossaryTerm[],
) {
  return request<DubbingProject>(baseUrl, token, `/voice/dubbing-projects/${dubbingProjectId}`, {
    method: "PATCH",
    body: JSON.stringify({
      segments: segments.map((segment) => ({
        id: segment.id,
        translated_text: segment.translated_text,
        voice_profile_id: segment.voice_profile_id,
        start_seconds: segment.start_seconds,
        end_seconds: segment.end_seconds,
        speech_rate: segment.speech_rate,
        audio_asset_id: segment.audio_asset_id,
        translation_approved: segment.translation_approved,
        segment_approved: segment.segment_approved,
      })),
      glossary,
    }),
  });
}

export function queueDubbingExport(
  baseUrl: string,
  token: string,
  dubbingProjectId: string,
  sourceVideoAssetId?: string,
) {
  return request<VoiceJob>(
    baseUrl,
    token,
    `/voice/dubbing-projects/${dubbingProjectId}/export`,
    {
      method: "POST",
      body: JSON.stringify({ source_video_asset_id: sourceVideoAssetId ?? null }),
    },
  );
}

export function regenerateDubbingSegment(
  baseUrl: string,
  token: string,
  dubbingProjectId: string,
  segmentId: string,
) {
  return request<void>(
    baseUrl,
    token,
    `/voice/dubbing-projects/${dubbingProjectId}/segments/${segmentId}/regenerate`,
    { method: "POST" },
  );
}

export async function downloadVoiceSubtitles(
  baseUrl: string,
  token: string,
  path: string,
  filename: string,
) {
  const response = await fetch(apiUrl(baseUrl, path), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as APIErrorResponse;
    throw new Error(body.error?.message ?? body.detail ?? `Subtitle export failed (${response.status}).`);
  }
  const objectUrl = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

export async function loadVoiceAudioPreview(
  baseUrl: string,
  token: string,
  assetId: string,
) {
  const response = await fetch(apiUrl(baseUrl, `/media/${assetId}/download`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error(`Could not load reference audio (${response.status}).`);
  return URL.createObjectURL(await response.blob());
}
