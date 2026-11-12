export type ContentProject = {
  id: string;
  name: string;
  description: string | null;
};

export type VisualStyle =
  | "realistic"
  | "cinematic"
  | "documentary"
  | "2d_animation"
  | "3d_animation"
  | "anime"
  | "cartoon"
  | "map_animation"
  | "product_commercial";

export type CameraMovement =
  | "static"
  | "pan_left"
  | "pan_right"
  | "tilt_up"
  | "tilt_down"
  | "dolly_in"
  | "dolly_out"
  | "tracking"
  | "orbit"
  | "handheld"
  | "crane"
  | "drone";

export type ProjectStory = {
  id: string;
  name: string;
  story_idea: string | null;
  story_outline: string | null;
  script_text: string | null;
  visual_settings: Record<string, unknown> | null;
  updated_at: string;
};

export type Character = {
  id: string;
  name: string;
  description: string | null;
  identity_description: string | null;
  outfit_settings: Record<string, unknown> | null;
  visual_traits: Record<string, unknown> | null;
  created_at: string;
};

export type Environment = {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  visual_traits: Record<string, unknown> | null;
  reference_asset_id: string | null;
  created_at: string;
};

export type SceneShot = {
  id: string;
  scene_id: string;
  order_index: number;
  description: string;
  shot_prompt: string | null;
  duration_seconds: number | null;
  camera_movement: CameraMovement | null;
  media_asset_id: string | null;
  first_frame_asset_id: string | null;
  last_frame_asset_id: string | null;
  generated_media_asset_id: string | null;
};

export type CharacterReference = {
  id: string;
  character_id: string;
  media_asset_id: string | null;
  reference_type: string;
  description: string | null;
  created_at: string;
};

export type Scene = {
  id: string;
  project_id: string;
  order_index: number;
  title: string;
  description: string | null;
  visual_style: VisualStyle | null;
  scene_prompt: string | null;
  duration_seconds: number;
  camera_movement: CameraMovement | null;
  lighting: string | null;
  color_palette: string | null;
  environment_id: string | null;
  character_ids: string[];
  first_frame_asset_id: string | null;
  last_frame_asset_id: string | null;
  generation_status: string;
  generation_job_id: string | null;
  generated_media_asset_id: string | null;
  generated_preview_label: string | null;
  generation_provider: string | null;
  is_approved: boolean;
  continuity_notes: string | null;
  shots: SceneShot[];
  created_at: string;
  updated_at: string;
};

export type ContentJob = {
  id: string;
  project_id: string | null;
  job_type: string;
  status: "queued" | "processing" | "completed" | "failed" | "cancelled";
  progress: number;
  model_name: string | null;
  model_version: string | null;
  model_license: string | null;
  commercial_use_permitted: boolean | null;
  generation_mode: string | null;
  generation_settings: Record<string, unknown> | null;
  worker_job_id: string | null;
  retry_count: number;
  max_retries: number;
  cancellation_requested: boolean;
  output_data: Record<string, unknown> | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};

export type GenerationModel = {
  id: string;
  model_name: string;
  model_version: string;
  repository: string | null;
  model_license: string;
  commercial_use_permitted: boolean | null;
  gpu_requirement: string;
  supported_languages: string[];
  generation_modes: ("text_to_video" | "image_to_video")[];
  installation_instructions: string;
  availability: "mock" | "operator_configured";
};

export type ContinuityReport = {
  project_id: string;
  scenes: { scene_id: string; scene_title: string; issues: string[] }[];
  issue_count: number;
};

export const CONTENT_API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "ai-creator-studio:media-token";

async function request<T>(token: string, path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init?.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(`${CONTENT_API_BASE}/api/v1${path}`, { ...init, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as {
      error?: { message?: string };
      detail?: string;
    };
    throw new Error(body.error?.message ?? body.detail ?? `Content Studio request failed (${response.status}).`);
  }
  if (response.status === 204) return undefined as T;
  return await response.json() as T;
}

export function getContentToken() {
  return window.sessionStorage.getItem(TOKEN_KEY) ?? "";
}

export function authenticateContent(email: string, password: string, createAccount: boolean) {
  return request<{ access_token: string }>("", `/auth/${createAccount ? "register" : "login"}`, {
    method: "POST",
    body: JSON.stringify(createAccount
      ? { email, password, full_name: email.split("@")[0] }
      : { email, password }),
  });
}

export function listContentProjects(token: string) {
  return request<ContentProject[]>(token, "/projects");
}

export function createContentProject(token: string, name: string) {
  return request<ContentProject>(token, "/projects", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function getProjectStory(token: string, projectId: string) {
  return request<ProjectStory>(token, `/projects/${projectId}/content`);
}

export function saveProjectStory(token: string, projectId: string, data: Partial<ProjectStory>) {
  return request<ProjectStory>(token, `/projects/${projectId}/content`, {
    method: "PUT",
    body: JSON.stringify({
      story_idea: data.story_idea,
      story_outline: data.story_outline,
      script_text: data.script_text,
      visual_settings: data.visual_settings,
    }),
  });
}

export function listCharacters(token: string, projectId: string) {
  return request<Character[]>(token, `/projects/${projectId}/characters`);
}

export function createCharacter(token: string, projectId: string, data: Partial<Character>) {
  return request<Character>(token, `/projects/${projectId}/characters`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function deleteCharacter(token: string, projectId: string, id: string) {
  return request<void>(token, `/projects/${projectId}/characters/${id}`, { method: "DELETE" });
}

export function updateCharacter(token: string, projectId: string, id: string, data: Partial<Character>) {
  return request<Character>(token, `/projects/${projectId}/characters/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export function listCharacterReferences(token: string, projectId: string, characterId: string) {
  return request<CharacterReference[]>(
    token,
    `/projects/${projectId}/characters/${characterId}/references`,
  );
}

export function addCharacterReference(
  token: string,
  projectId: string,
  characterId: string,
  data: { media_asset_id: string; reference_type: string; description?: string },
) {
  return request<CharacterReference>(
    token,
    `/projects/${projectId}/characters/${characterId}/references`,
    { method: "POST", body: JSON.stringify(data) },
  );
}

export function listEnvironments(token: string, projectId: string) {
  return request<Environment[]>(token, `/projects/${projectId}/environments`);
}

export function createEnvironment(token: string, projectId: string, data: Partial<Environment>) {
  return request<Environment>(token, `/projects/${projectId}/environments`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateEnvironment(token: string, projectId: string, id: string, data: Partial<Environment>) {
  return request<Environment>(token, `/projects/${projectId}/environments/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export function deleteEnvironment(token: string, projectId: string, id: string) {
  return request<void>(token, `/projects/${projectId}/environments/${id}`, { method: "DELETE" });
}

export function listScenes(token: string, projectId: string) {
  return request<Scene[]>(token, `/projects/${projectId}/scenes`);
}

export function createScene(token: string, projectId: string, data: Record<string, unknown>) {
  return request<Scene>(token, `/projects/${projectId}/scenes`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateScene(token: string, projectId: string, id: string, data: Record<string, unknown>) {
  return request<Scene>(token, `/projects/${projectId}/scenes/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export function deleteScene(token: string, projectId: string, id: string) {
  return request<void>(token, `/projects/${projectId}/scenes/${id}`, { method: "DELETE" });
}

export function updateSceneApproval(token: string, projectId: string, sceneId: string, is_approved: boolean) {
  return request<Scene>(token, `/projects/${projectId}/scenes/${sceneId}/approval`, {
    method: "POST",
    body: JSON.stringify({ is_approved }),
  });
}

export function addSceneShot(
  token: string,
  projectId: string,
  sceneId: string,
  description: string,
  mediaAssetId: string | null,
) {
  return request<SceneShot>(token, `/projects/${projectId}/scenes/${sceneId}/shots`, {
    method: "POST",
    body: JSON.stringify({ description, media_asset_id: mediaAssetId }),
  });
}

export function updateSceneShot(
  token: string,
  projectId: string,
  sceneId: string,
  shotId: string,
  data: Partial<SceneShot>,
) {
  return request<SceneShot>(
    token,
    `/projects/${projectId}/scenes/${sceneId}/shots/${shotId}`,
    { method: "PATCH", body: JSON.stringify(data) },
  );
}

export function getContinuityReport(token: string, projectId: string) {
  return request<ContinuityReport>(token, `/projects/${projectId}/continuity`);
}

export function getSceneProvider(token: string, projectId: string) {
  return request<{ available: boolean; provider: string | null; preview_only: boolean }>(
    token,
    `/projects/${projectId}/scene-provider`,
  );
}

export function getContentJob(token: string, jobId: string) {
  return request<ContentJob>(token, `/content/jobs/${jobId}`);
}

export function getGenerationModels(token: string) {
  return request<GenerationModel[]>(token, "/content/models");
}

export function cancelContentJob(token: string, jobId: string) {
  return request<ContentJob>(token, `/content/jobs/${jobId}/cancel`, { method: "POST" });
}

export function retryContentJob(token: string, jobId: string) {
  return request<ContentJob>(token, `/content/jobs/${jobId}/retry`, { method: "POST" });
}

export function queueSceneGeneration(
  token: string,
  projectId: string,
  sceneId: string,
  data: {
    generation_mode: "text_to_video" | "image_to_video";
    model_id: string;
    settings: Record<string, unknown>;
  },
) {
  return request<ContentJob>(token, `/projects/${projectId}/scenes/${sceneId}/generate`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function assembleStoryboard(token: string, projectId: string) {
  return request<{ timeline_id: string; message: string; video_asset_count: number }>(
    token,
    `/projects/${projectId}/storyboard/assemble`,
    { method: "POST" },
  );
}
