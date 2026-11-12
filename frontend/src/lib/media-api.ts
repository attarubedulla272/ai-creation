export type MediaAsset = {
  id: string;
  project_id: string | null;
  name: string;
  media_type: "video" | "audio" | "image";
  content_type: string;
  file_size: number;
  duration_seconds: number | null;
  metadata_json: {
    probe?: {
      width?: number | null;
      height?: number | null;
      frame_rate?: number | null;
      video_codec?: string | null;
      format_name?: string | null;
      audio_streams?: { codec?: string | null }[];
    };
    derivatives?: Record<string, string>;
    processing_job_id?: string;
  } | null;
};

export type MediaJob = {
  id: string;
  job_type: string;
  status: "queued" | "processing" | "completed" | "failed" | "cancelled";
  progress: number;
  error_message: string | null;
  retry_count: number;
  max_retries: number;
  cancellation_requested: boolean;
};

export type UploadedMedia = {
  asset: MediaAsset;
  job_id: string;
};

type APIErrorResponse = {
  error?: { message?: string };
  detail?: string;
};

function apiUrl(baseUrl: string, path: string) {
  return `${baseUrl.replace(/\/+$/, "")}/api/v1${path}`;
}

async function responseError(response: Response) {
  const body = await response.json().catch(() => ({})) as APIErrorResponse;
  throw new Error(body.error?.message ?? body.detail ?? `Backend request failed (${response.status}).`);
}

export async function authenticate(
  baseUrl: string,
  email: string,
  password: string,
  createAccount: boolean,
) {
  if (createAccount) {
    const registration = await fetch(apiUrl(baseUrl, "/auth/register"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!registration.ok) await responseError(registration);
  }
  const response = await fetch(apiUrl(baseUrl, "/auth/login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) await responseError(response);
  return (await response.json() as { access_token: string }).access_token;
}

export async function listMedia(baseUrl: string, token: string) {
  const response = await fetch(apiUrl(baseUrl, "/media"), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) await responseError(response);
  return await response.json() as MediaAsset[];
}

export function uploadMedia(
  baseUrl: string,
  token: string,
  file: File,
  onProgress: (progress: number) => void,
  projectId?: string,
) {
  return new Promise<UploadedMedia>((resolve, reject) => {
    const request = new XMLHttpRequest();
    const uploadUrl = new URL(apiUrl(baseUrl, "/media"));
    if (projectId) uploadUrl.searchParams.set("project_id", projectId);
    request.open("POST", uploadUrl.toString());
    request.setRequestHeader("Authorization", `Bearer ${token}`);
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    });
    request.addEventListener("load", () => {
      let body: UploadedMedia | APIErrorResponse;
      try {
        body = JSON.parse(request.responseText) as UploadedMedia | APIErrorResponse;
      } catch {
        reject(new Error(`Backend returned an unreadable response (${request.status}).`));
        return;
      }
      if (request.status < 200 || request.status >= 300) {
        const errorBody = body as APIErrorResponse;
        reject(new Error(errorBody.error?.message ?? errorBody.detail ?? `Upload failed (${request.status}).`));
        return;
      }
      resolve(body as UploadedMedia);
    });
    request.addEventListener("error", () => reject(new Error("Could not reach the media backend.")));
    request.addEventListener("abort", () => reject(new Error("Upload was interrupted.")));
    const form = new FormData();
    form.append("file", file);
    request.send(form);
  });
}

export async function getMediaJob(baseUrl: string, token: string, jobId: string) {
  const response = await fetch(apiUrl(baseUrl, `/media/jobs/${jobId}`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) await responseError(response);
  return await response.json() as MediaJob;
}

export async function retryMediaJob(baseUrl: string, token: string, jobId: string) {
  const response = await fetch(apiUrl(baseUrl, `/media/jobs/${jobId}/retry`), {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) await responseError(response);
  return await response.json() as MediaJob;
}

export async function cancelMediaJob(baseUrl: string, token: string, jobId: string) {
  const response = await fetch(apiUrl(baseUrl, `/media/jobs/${jobId}/cancel`), {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) await responseError(response);
  return await response.json() as MediaJob;
}

export async function deleteMedia(baseUrl: string, token: string, assetId: string) {
  const response = await fetch(apiUrl(baseUrl, `/media/${assetId}`), {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) await responseError(response);
}

export async function loadMediaDerivative(
  baseUrl: string,
  token: string,
  assetId: string,
  derivative: "thumbnail" | "proxy" | "waveform",
) {
  const response = await fetch(apiUrl(
    baseUrl,
    `/media/${assetId}/derivatives/${derivative}`,
  ), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) await responseError(response);
  return URL.createObjectURL(await response.blob());
}

export async function loadMediaPreview(
  baseUrl: string,
  token: string,
  assetId: string,
) {
  const response = await fetch(apiUrl(baseUrl, `/media/${assetId}/download`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) await responseError(response);
  return URL.createObjectURL(await response.blob());
}

export async function downloadMedia(
  baseUrl: string,
  token: string,
  assetId: string,
  derivative?: string,
) {
  const path = derivative
    ? `/media/${assetId}/derivatives/${encodeURIComponent(derivative)}`
    : `/media/${assetId}/download`;
  const response = await fetch(apiUrl(baseUrl, path), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) await responseError(response);
  const blobUrl = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = blobUrl;
  const derivativeNames: Record<string, string> = {
    thumbnail: "thumbnail.jpg",
    proxy: "proxy.mp4",
    extracted_audio: "audio.m4a",
    waveform: "waveform.png",
  };
  anchor.download = derivative ? derivativeNames[derivative] ?? "media" : "media";
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
}
