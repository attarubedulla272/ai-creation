import type { MediaAsset } from "@/lib/media-api";

export type PublicationStatus = "draft" | "ready" | "scheduled" | "published";
export type PublicationPlatform = "youtube" | "instagram" | "tiktok" | "other";

export type Publication = {
  id: string;
  project_id: string;
  platform: PublicationPlatform;
  title: string | null;
  description: string | null;
  status: PublicationStatus;
  scheduled_at: string | null;
  published_at: string | null;
  external_id: string | null;
  metadata_json: {
    tags?: string[];
    hashtags?: string[];
    primary_keywords?: string[];
    secondary_keywords?: string[];
    chapters?: Array<{ timestamp_seconds: number; title: string }>;
    language?: string | null;
    category?: string | null;
  } | null;
  media_asset_id: string | null;
  clip_candidate_id: string | null;
  thumbnail_asset_id: string | null;
  version: number;
  youtube_status: string | null;
  youtube_privacy_status: "private" | "unlisted" | "public" | null;
  youtube_url: string | null;
  created_at: string;
  updated_at: string;
};

export type PublicationInput = {
  platform: PublicationPlatform;
  title: string;
  description: string;
  tags: string[];
  hashtags: string[];
  primary_keywords: string[];
  secondary_keywords: string[];
  chapters: Array<{ timestamp_seconds: number; title: string }>;
  language: string | null;
  category: string | null;
  media_asset_id: string | null;
  clip_candidate_id: string | null;
  thumbnail_asset_id: string | null;
  status: Exclude<PublicationStatus, "published">;
  scheduled_at: string | null;
};

export type PublicationRevision = {
  id: string;
  publication_id: string;
  version: number;
  snapshot: Record<string, unknown>;
  created_at: string;
};

export type YouTubeConnection = {
  id: string;
  channel_id: string;
  channel_title: string;
  channel_custom_url: string | null;
  status: "connected" | "reauthorization_required";
  analytics_enabled: boolean;
};

export type YouTubeUploadJob = {
  id: string;
  input_data: {
    publication_id: string;
    connection_id: string;
    privacy_status: "private" | "unlisted" | "public";
    publish_at: string | null;
  } | null;
  status: "queued" | "processing" | "completed" | "failed" | "cancelled";
  progress: number;
  output_data: Record<string, unknown> | null;
  error_message: string | null;
  retry_count: number;
  max_retries: number;
  cancellation_requested: boolean;
  created_at: string;
  updated_at: string;
};

export type YouTubeAnalytics = {
  daily: {
    columnHeaders?: Array<{ name: string; type?: string }>;
    rows?: Array<Array<string | number>>;
  };
  traffic_sources: {
    columnHeaders?: Array<{ name: string; type?: string }>;
    rows?: Array<Array<string | number>>;
  };
  available_through: string | null;
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
    throw new Error(body.error?.message ?? body.detail ?? `Publishing request failed (${response.status}).`);
  }
  return await response.json() as T;
}

export function listPublications(baseUrl: string, token: string, projectId: string) {
  return request<Publication[]>(
    baseUrl,
    token,
    `/publishing/projects/${projectId}/publications`,
  );
}

export function listPublicationCalendar(baseUrl: string, token: string) {
  return request<Publication[]>(baseUrl, token, "/publishing/calendar");
}

export function createPublication(
  baseUrl: string,
  token: string,
  projectId: string,
  input: PublicationInput,
) {
  return request<Publication>(baseUrl, token, `/publishing/projects/${projectId}/publications`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updatePublication(
  baseUrl: string,
  token: string,
  publicationId: string,
  input: PublicationInput,
) {
  return request<Publication>(baseUrl, token, `/publishing/publications/${publicationId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function getPublicationRevisions(baseUrl: string, token: string, publicationId: string) {
  return request<PublicationRevision[]>(
    baseUrl,
    token,
    `/publishing/publications/${publicationId}/revisions`,
  );
}

export function getPublishingCapabilities(baseUrl: string, token: string) {
  return request<{
    youtube: { available: boolean; reason: string; official_docs: string[] };
    analytics: { available: boolean; reason: string; official_docs: string[] };
  }>(baseUrl, token, "/publishing/capabilities");
}

export function suggestPublicationTitles(
  baseUrl: string,
  token: string,
  topic: string,
  keywords: string[],
) {
  return request<{ suggestions: string[]; method: "local_templates" }>(
    baseUrl,
    token,
    "/publishing/title-suggestions",
    { method: "POST", body: JSON.stringify({ topic, keywords }) },
  );
}

export function renderThumbnail(
  baseUrl: string,
  token: string,
  projectId: string,
  input: {
    source_asset_id: string;
    title: string;
    aspect_ratio: "16:9" | "1:1" | "9:16";
    text_position: "top" | "center" | "bottom";
    font_size: number;
    text_color: string;
    crop_x: number;
    crop_y: number;
  },
) {
  return request<{
    asset_id: string;
    name: string;
    width: number;
    height: number;
    content_type: string;
  }>(baseUrl, token, `/publishing/projects/${projectId}/thumbnails`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function listPublishingMedia(baseUrl: string, token: string) {
  const response = await fetch(endpoint(baseUrl, "/media"), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as APIErrorResponse;
    throw new Error(body.error?.message ?? body.detail ?? `Media request failed (${response.status}).`);
  }
  return await response.json() as MediaAsset[];
}

export function listYouTubeConnections(baseUrl: string, token: string) {
  return request<YouTubeConnection[]>(baseUrl, token, "/publishing/youtube/connections");
}

export function beginYouTubeConnection(baseUrl: string, token: string) {
  return request<{ authorization_url: string }>(
    baseUrl,
    token,
    "/publishing/youtube/connect",
    { method: "POST" },
  );
}

export function beginYouTubeAnalyticsAuthorization(
  baseUrl: string,
  token: string,
  connectionId: string,
) {
  return request<{ authorization_url: string }>(
    baseUrl,
    token,
    `/publishing/youtube/connections/${connectionId}/analytics/authorize`,
    { method: "POST" },
  );
}

export function disconnectYouTubeChannel(
  baseUrl: string,
  token: string,
  connectionId: string,
) {
  return request<{ disconnected: boolean; provider_revoked: boolean; warning: string | null }>(
    baseUrl,
    token,
    `/publishing/youtube/connections/${connectionId}/disconnect`,
    { method: "POST" },
  );
}

export function listYouTubeUploads(baseUrl: string, token: string) {
  return request<YouTubeUploadJob[]>(baseUrl, token, "/publishing/youtube/uploads");
}

export function createYouTubeUpload(
  baseUrl: string,
  token: string,
  publicationId: string,
  input: {
    connection_id: string;
    privacy_status: "private" | "unlisted" | "public";
    publish_at: string | null;
  },
) {
  return request<YouTubeUploadJob>(
    baseUrl,
    token,
    `/publishing/youtube/publications/${publicationId}/uploads`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

export function cancelYouTubeUpload(baseUrl: string, token: string, jobId: string) {
  return request<YouTubeUploadJob>(
    baseUrl,
    token,
    `/publishing/youtube/uploads/${jobId}/cancel`,
    { method: "POST" },
  );
}

export function retryYouTubeUpload(baseUrl: string, token: string, jobId: string) {
  return request<YouTubeUploadJob>(
    baseUrl,
    token,
    `/publishing/youtube/uploads/${jobId}/retry`,
    { method: "POST" },
  );
}

export function uploadYouTubeThumbnail(
  baseUrl: string,
  token: string,
  publicationId: string,
) {
  return request<{ uploaded: boolean }>(
    baseUrl,
    token,
    `/publishing/youtube/publications/${publicationId}/thumbnail`,
    { method: "POST" },
  );
}

export function getYouTubeAnalytics(
  baseUrl: string,
  token: string,
  connectionId: string,
  startDate?: string,
  endDate?: string,
) {
  const query = new URLSearchParams({ connection_id: connectionId });
  if (startDate) query.set("start_date", startDate);
  if (endDate) query.set("end_date", endDate);
  return request<YouTubeAnalytics>(
    baseUrl,
    token,
    `/publishing/youtube/analytics?${query.toString()}`,
  );
}
