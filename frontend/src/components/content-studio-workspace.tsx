"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import {
  Check,
  Clapperboard,
  FileText,
  Image as ImageIcon,
  LoaderCircle,
  Plus,
  RefreshCw,
  Save,
  Sparkles,
  Trash2,
} from "lucide-react";
import { Badge, Button, Card, Field, SectionHeading, SelectInput, TextInput } from "@/components/ui";
import { useStudioUI } from "@/components/studio-shell";
import { authenticate, listMedia, type MediaAsset } from "@/lib/media-api";
import {
  addCharacterReference,
  addSceneShot,
  assembleStoryboard,
  createCharacter,
  createContentProject,
  createEnvironment,
  createScene,
  cancelContentJob,
  deleteCharacter,
  deleteEnvironment,
  deleteScene,
  getContentJob,
  getGenerationModels,
  getContentToken,
  getContinuityReport,
  getProjectStory,
  getSceneProvider,
  listCharacters,
  listCharacterReferences,
  listContentProjects,
  listEnvironments,
  listScenes,
  queueSceneGeneration,
  retryContentJob,
  saveProjectStory,
  updateCharacter,
  updateEnvironment,
  updateScene,
  updateSceneApproval,
  updateSceneShot,
  type CameraMovement,
  type Character,
  type CharacterReference,
  type ContentJob,
  type ContentProject,
  type ContinuityReport,
  type Environment,
  type GenerationModel,
  type ProjectStory,
  type Scene,
  type VisualStyle,
  CONTENT_API_BASE,
} from "@/lib/content-api";

const STYLES: { value: VisualStyle; label: string }[] = [
  { value: "realistic", label: "Realistic" },
  { value: "cinematic", label: "Cinematic" },
  { value: "documentary", label: "Documentary" },
  { value: "2d_animation", label: "2D animation" },
  { value: "3d_animation", label: "3D animation" },
  { value: "anime", label: "Anime" },
  { value: "cartoon", label: "Cartoon" },
  { value: "map_animation", label: "Map animation" },
  { value: "product_commercial", label: "Product commercial" },
];

const CAMERA_MOVEMENTS: { value: CameraMovement; label: string }[] = [
  { value: "static", label: "Static" },
  { value: "pan_left", label: "Pan left" },
  { value: "pan_right", label: "Pan right" },
  { value: "tilt_up", label: "Tilt up" },
  { value: "tilt_down", label: "Tilt down" },
  { value: "dolly_in", label: "Dolly in" },
  { value: "dolly_out", label: "Dolly out" },
  { value: "tracking", label: "Tracking" },
  { value: "orbit", label: "Orbit" },
  { value: "handheld", label: "Handheld" },
  { value: "crane", label: "Crane" },
  { value: "drone", label: "Drone" },
];

const EMPTY_STORY: ProjectStory = {
  id: "",
  name: "",
  story_idea: "",
  story_outline: "",
  script_text: "",
  visual_settings: {},
  updated_at: "",
};

function jsonField(value: Record<string, unknown> | null | undefined, key: string) {
  const field = value?.[key];
  return typeof field === "string" ? field : "";
}

function providerJobStatus(job: ContentJob) {
  if (job.status === "completed" && job.output_data?.preview_only === true) {
    return "Text-only mock preview complete; no image or video was generated.";
  }
  return job.error_message ?? `Scene job ${job.status}.`;
}

function sceneUpdatePayload(scene: Scene) {
  return {
    title: scene.title,
    description: scene.description,
    scene_prompt: scene.scene_prompt,
    duration_seconds: scene.duration_seconds,
    order_index: scene.order_index,
    visual_style: scene.visual_style,
    camera_movement: scene.camera_movement,
    lighting: scene.lighting,
    color_palette: scene.color_palette,
    environment_id: scene.environment_id,
    character_ids: scene.character_ids,
    first_frame_asset_id: scene.first_frame_asset_id,
    last_frame_asset_id: scene.last_frame_asset_id,
    continuity_notes: scene.continuity_notes,
  };
}

export function ContentStudioWorkspace({ current }: { current: string }) {
  const { notify } = useStudioUI();
  const [token, setToken] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [createAccount, setCreateAccount] = useState(false);
  const [projects, setProjects] = useState<ContentProject[]>([]);
  const [projectId, setProjectId] = useState("");
  const [story, setStory] = useState<ProjectStory>(EMPTY_STORY);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [environments, setEnvironments] = useState<Environment[]>([]);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [media, setMedia] = useState<MediaAsset[]>([]);
  const [continuity, setContinuity] = useState<ContinuityReport | null>(null);
  const [provider, setProvider] = useState<{ available: boolean; provider: string | null; preview_only: boolean } | null>(null);
  const [models, setModels] = useState<GenerationModel[]>([]);
  const [modelId, setModelId] = useState("operator-configured");
  const [generationModes, setGenerationModes] = useState<Record<string, "text_to_video" | "image_to_video">>({});
  const [resolution, setResolution] = useState("1280x720");
  const [frameRate, setFrameRate] = useState("24");
  const [activeJob, setActiveJob] = useState<ContentJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [projectName, setProjectName] = useState("");
  const [newCharacterName, setNewCharacterName] = useState("");
  const [newEnvironmentName, setNewEnvironmentName] = useState("");
  const [shotDescription, setShotDescription] = useState("");
  const [shotVideoId, setShotVideoId] = useState("");
  const [referenceSelections, setReferenceSelections] = useState<Record<string, string>>({});
  const [characterRefs, setCharacterRefs] = useState<Record<string, CharacterReference[]>>({});

  const selectedProject = projects.find((project) => project.id === projectId) ?? null;
  const selectedScene = scenes[0] ?? null;
  const selectedModel = models.find((model) => model.id === modelId);
  const projectMedia = useMemo(
    () => media.filter((asset) => asset.project_id === null || asset.project_id === projectId),
    [media, projectId],
  );
  const videos = useMemo(() => projectMedia.filter((asset) => asset.media_type === "video"), [projectMedia]);
  const images = useMemo(() => projectMedia.filter((asset) => asset.media_type === "image"), [projectMedia]);

  useEffect(() => {
    void Promise.resolve().then(() => {
      const savedToken = getContentToken();
      if (savedToken) setToken(savedToken);
    });
  }, []);

  const refresh = useCallback(async (activeToken: string, selectedProjectId?: string) => {
    const loadedProjects = await listContentProjects(activeToken);
    setProjects(loadedProjects);
    const nextProjectId = selectedProjectId && loadedProjects.some((item) => item.id === selectedProjectId)
      ? selectedProjectId
      : loadedProjects[0]?.id ?? "";
    setProjectId(nextProjectId);
    const loadedMedia = await listMedia(CONTENT_API_BASE, activeToken);
    setMedia(loadedMedia);
    if (!nextProjectId) {
      setStory(EMPTY_STORY);
      setCharacters([]);
      setEnvironments([]);
      setScenes([]);
      return;
    }
    const [projectStory, projectCharacters, projectEnvironments, projectScenes, providerStatus, registry] =
      await Promise.all([
        getProjectStory(activeToken, nextProjectId),
        listCharacters(activeToken, nextProjectId),
        listEnvironments(activeToken, nextProjectId),
        listScenes(activeToken, nextProjectId),
        getSceneProvider(activeToken, nextProjectId),
        getGenerationModels(activeToken),
      ]);
    setStory(projectStory);
    setCharacters(projectCharacters);
    setEnvironments(projectEnvironments);
    setScenes(projectScenes);
    setProvider(providerStatus);
    setModels(registry);
    const runningJob = projectScenes.find(
      (scene) => scene.generation_job_id && ["queued", "processing"].includes(scene.generation_status),
    )?.generation_job_id;
    if (runningJob) setActiveJob(await getContentJob(activeToken, runningJob));
  }, []);

  useEffect(() => {
    if (!token) return;
    let active = true;
    void Promise.resolve().then(() => {
      if (!active) return;
      return refresh(token, projectId || undefined).catch((loadError: unknown) => {
        if (active) setError(loadError instanceof Error ? loadError.message : "Could not load Content Studio.");
      });
    });
    return () => {
      active = false;
    };
  }, [projectId, refresh, token]);

  useEffect(() => {
    if (!token || !activeJob || ["completed", "failed", "cancelled"].includes(activeJob.status)) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const job = await getContentJob(token, activeJob.id);
        if (!active) return;
        setActiveJob(job);
        if (["completed", "failed", "cancelled"].includes(job.status)) {
          notify(providerJobStatus(job), job.status === "failed" ? "error" : "success");
          await refresh(token, projectId);
        } else {
          timer = setTimeout(poll, 800);
        }
      } catch (pollError) {
        if (active) setError(pollError instanceof Error ? pollError.message : "Could not refresh scene job.");
      }
    };
    timer = setTimeout(poll, 500);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [activeJob, notify, projectId, refresh, token]);

  const run = async (operation: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await operation();
    } catch (operationError) {
      setError(operationError instanceof Error ? operationError.message : "Content Studio action failed.");
    } finally {
      setBusy(false);
    }
  };

  const signIn = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await run(async () => {
      const newToken = await authenticate(CONTENT_API_BASE, email, password, createAccount);
      window.sessionStorage.setItem("ai-creator-studio:media-token", newToken);
      setToken(newToken);
      await refresh(newToken);
      notify(createAccount ? "Account created and signed in." : "Signed in to Content Studio.");
    });
  };

  const createProject = async () => {
    if (!projectName.trim()) return;
    await run(async () => {
      const project = await createContentProject(token, projectName.trim());
      setProjectName("");
      await refresh(token, project.id);
      notify("Project created.");
    });
  };

  const saveStory = async () => {
    if (!projectId) return;
    await run(async () => {
      const saved = await saveProjectStory(token, projectId, story);
      setStory(saved);
      notify("Story and style settings saved.");
    });
  };

  const createNewScene = async () => {
    if (!projectId) return;
    await run(async () => {
      const created = await createScene(token, projectId, {
        title: `Scene ${scenes.length + 1}`,
        description: "",
        scene_prompt: "",
        order_index: scenes.length,
        duration_seconds: 5,
        visual_style: jsonField(story.visual_settings, "visual_style") || null,
      });
      setScenes((previous) => [...previous, created]);
      notify("Scene added to the storyboard.");
    });
  };

  const saveScene = async (scene: Scene) => {
    await run(async () => {
      const updated = await updateScene(token, projectId, scene.id, sceneUpdatePayload(scene));
      setScenes((previous) => previous.map((item) => item.id === updated.id ? updated : item));
      notify("Scene plan saved.");
    });
  };

  const changeScene = (sceneId: string, changes: Partial<Scene>) => {
    setScenes((previous) => previous.map((scene) => scene.id === sceneId ? { ...scene, ...changes } : scene));
  };

  const generateScene = async (scene: Scene) => {
    await run(async () => {
      const generation_mode = generationModes[scene.id] ?? "text_to_video";
      if (generation_mode === "image_to_video" && !scene.first_frame_asset_id) {
        throw new Error("Select a first-frame reference image for image-to-video generation.");
      }
      const savedScene = await updateScene(token, projectId, scene.id, sceneUpdatePayload(scene));
      setScenes((previous) => previous.map((item) => item.id === savedScene.id ? savedScene : item));
      const job = await queueSceneGeneration(token, projectId, scene.id, {
        generation_mode,
        model_id: modelId,
        settings: { resolution, frame_rate: Number(frameRate) },
      });
      setActiveJob(job);
      setScenes((previous) => previous.map((item) => item.id === scene.id
        ? { ...item, generation_status: "queued", generated_preview_label: null }
        : item));
      notify("One scene was queued; other scenes are unchanged.");
    });
  };

  const cancelActiveJob = async () => {
    if (!activeJob) return;
    await run(async () => {
      const job = await cancelContentJob(token, activeJob.id);
      setActiveJob(job);
      notify(job.status === "cancelled" ? "Queued job cancelled." : "Cancellation requested from the GPU worker.");
    });
  };

  const retryActiveJob = async () => {
    if (!activeJob) return;
    await run(async () => {
      const job = await retryContentJob(token, activeJob.id);
      setActiveJob(job);
      await refresh(token, projectId);
      notify(`Retry ${job.retry_count} of ${job.max_retries} queued.`);
    });
  };

  const addCharacter = async () => {
    if (!newCharacterName.trim()) return;
    await run(async () => {
      const character = await createCharacter(token, projectId, {
        name: newCharacterName.trim(),
        identity_description: "",
        outfit_settings: {},
        visual_traits: {},
      });
      setCharacters((previous) => [...previous, character]);
      setNewCharacterName("");
      notify("Character added to the Character Bible.");
    });
  };

  const addEnvironment = async () => {
    if (!newEnvironmentName.trim()) return;
    await run(async () => {
      const environment = await createEnvironment(token, projectId, {
        name: newEnvironmentName.trim(),
        visual_traits: {},
      });
      setEnvironments((previous) => [...previous, environment]);
      setNewEnvironmentName("");
      notify("Environment added.");
    });
  };

  const addShot = async () => {
    if (!selectedScene || !shotDescription.trim()) return;
    await run(async () => {
      const shot = await addSceneShot(
        token,
        projectId,
        selectedScene.id,
        shotDescription.trim(),
        shotVideoId || null,
      );
      setScenes((previous) => previous.map((scene) => scene.id === selectedScene.id
        ? { ...scene, shots: [...scene.shots, shot] }
        : scene));
      setShotDescription("");
      setShotVideoId("");
      notify("Shot added to the selected scene.");
    });
  };

  const reviewContinuity = async () => {
    await run(async () => setContinuity(await getContinuityReport(token, projectId)));
  };

  const assemble = async () => {
    await run(async () => {
      const result = await assembleStoryboard(token, projectId);
      notify(result.message);
    });
  };

  const updateStoryField = (field: "story_idea" | "story_outline" | "script_text", value: string) => {
    setStory((previous) => ({ ...previous, [field]: value }));
  };

  const updateStyle = (key: string, value: string) => {
    setStory((previous) => ({
      ...previous,
      visual_settings: { ...(previous.visual_settings ?? {}), [key]: value },
    }));
  };

  const addReference = async (characterId: string) => {
    const assetId = referenceSelections[characterId];
    if (!assetId) return;
    await run(async () => {
      const reference = await addCharacterReference(token, projectId, characterId, {
        media_asset_id: assetId,
        reference_type: "character_sheet",
        description: "Uploaded character reference sheet.",
      });
      setCharacterRefs((previous) => ({
        ...previous,
        [characterId]: [...(previous[characterId] ?? []), reference],
      }));
      notify("Character reference added.");
    });
  };

  useEffect(() => {
    if (!token || !projectId || current !== "Character Bible") return;
    let active = true;
    void Promise.all(characters.map(async (character) => ({
      id: character.id,
      references: await listCharacterReferences(token, projectId, character.id),
    }))).then((results) => {
      if (active) setCharacterRefs(Object.fromEntries(results.map(({ id, references }) => [id, references])));
    }).catch((loadError: unknown) => {
      if (active) setError(loadError instanceof Error ? loadError.message : "Could not load character references.");
    });
    return () => { active = false; };
  }, [characters, current, projectId, token]);

  if (!token) {
    return (
      <Card className="workspace-main-card">
        <SectionHeading title="Connect to your local backend" description="Sign in to save Script-to-Film planning data to your local database." />
        <form className="content-auth-form" onSubmit={(event) => void signIn(event)}>
          <Field label="Email"><TextInput autoComplete="email" onChange={(event) => setEmail(event.target.value)} required type="email" value={email} /></Field>
          <Field label="Password"><TextInput autoComplete={createAccount ? "new-password" : "current-password"} onChange={(event) => setPassword(event.target.value)} required type="password" value={password} /></Field>
          <label className="content-checkbox"><input checked={createAccount} onChange={(event) => setCreateAccount(event.target.checked)} type="checkbox" /> Create a new account</label>
          <Button disabled={busy} type="submit" variant="primary">{busy ? "Connecting..." : createAccount ? "Create account" : "Sign in"}</Button>
        </form>
        {error ? <p className="content-error" role="alert">{error}</p> : null}
      </Card>
    );
  }

  if (!projectId) {
    return (
      <Card className="workspace-main-card">
        <SectionHeading title="Create a Script-to-Film project" description="Projects and creative planning are saved in your local backend." />
        <div className="content-inline-form">
          <TextInput aria-label="Project name" onChange={(event) => setProjectName(event.target.value)} placeholder="Project name" value={projectName} />
          <Button disabled={busy || !projectName.trim()} icon={<Plus size={15} />} onClick={() => void createProject()} variant="primary">Create project</Button>
        </div>
        {error ? <p className="content-error" role="alert">{error}</p> : null}
      </Card>
    );
  }

  return (
    <div className="content-studio-workspace">
      <Card className="content-project-bar">
        <div className="content-project-select">
          <Field label="Project">
            <SelectInput onChange={(event) => setProjectId(event.target.value)} value={projectId}>
              {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
            </SelectInput>
          </Field>
        </div>
        <div className="content-inline-form">
          <TextInput aria-label="New project name" onChange={(event) => setProjectName(event.target.value)} placeholder="New project name" value={projectName} />
          <Button disabled={busy || !projectName.trim()} icon={<Plus size={14} />} onClick={() => void createProject()} size="sm">New project</Button>
        </div>
        <Badge tone={provider?.available ? "violet" : "amber"}>
          {provider?.available ? provider.provider ?? "Worker connected" : "No generation worker"}
        </Badge>
      </Card>

      {error ? <p className="content-error" role="alert">{error}</p> : null}
      {activeJob ? (
        <div aria-live="polite" className="content-job-banner">
          {!["completed", "failed", "cancelled"].includes(activeJob.status) ? <LoaderCircle className="content-spinner" size={15} /> : null}
          <span>
            Scene job {activeJob.status} · {activeJob.progress}% · {activeJob.model_name ?? "Unknown model"}
            {activeJob.model_version ? ` ${activeJob.model_version}` : ""}
            {activeJob.cancellation_requested ? " · cancellation requested" : ""}
            {activeJob.error_message ? ` · ${activeJob.error_message}` : ""}
          </span>
          {["queued", "processing"].includes(activeJob.status) ? <Button disabled={busy} onClick={() => void cancelActiveJob()} size="sm">Cancel</Button> : null}
          {["failed", "cancelled"].includes(activeJob.status) && activeJob.retry_count < activeJob.max_retries ? <Button disabled={busy} icon={<RefreshCw size={13} />} onClick={() => void retryActiveJob()} size="sm">Retry</Button> : null}
        </div>
      ) : null}
      {!selectedProject ? null : current === "Brief" || current === "Script" ? (
        <div className="workspace-columns content-workspace-columns">
          <Card className="workspace-main-card">
            <SectionHeading
              title={current === "Brief" ? "Idea and story outline" : "Script editor"}
              description="Draft and save story material locally. No AI writing service is connected."
              action={<Button disabled={busy} icon={<Save size={14} />} onClick={() => void saveStory()} size="sm" variant="primary">Save project</Button>}
            />
            {current === "Brief" ? (
              <>
                <Field label="Core idea" hint="A concise description of the story.">
                  <textarea className="text-area brief-area" maxLength={10_000} onChange={(event) => updateStoryField("story_idea", event.target.value)} value={story.story_idea ?? ""} />
                </Field>
                <Field label="Story outline" hint="Organize the beginning, middle, and ending.">
                  <textarea className="text-area script-area" maxLength={50_000} onChange={(event) => updateStoryField("story_outline", event.target.value)} value={story.story_outline ?? ""} />
                </Field>
              </>
            ) : (
              <Field label="Script" hint="Script text is persisted with the project.">
                <textarea className="text-area script-area content-script-area" maxLength={100_000} onChange={(event) => updateStoryField("script_text", event.target.value)} value={story.script_text ?? ""} />
              </Field>
            )}
          </Card>
          <Card className="workspace-aside-card">
            <SectionHeading title="Planning workflow" />
            <div className="detail-list">
              <div><span>Project</span><strong>{selectedProject.name}</strong></div>
              <div><span>Scenes</span><strong>{scenes.length}</strong></div>
              <div><span>Characters</span><strong>{characters.length}</strong></div>
              <div><span>Environments</span><strong>{environments.length}</strong></div>
            </div>
            <div className="notice-strip"><FileText size={14} /><span>Saving persists your edits. AI research and script generation are not connected.</span></div>
          </Card>
        </div>
      ) : current === "Model Registry" ? (
        <div className="workspace-main-stack">
          <Card className="workspace-main-card">
            <SectionHeading title="Generation model registry" description="Catalog entries are metadata only. Model weights are never downloaded by the API or development Mac." />
            {models.map((model) => (
              <article className="content-entity-card" key={model.id}>
                <div className="content-entity-heading">
                  <h3>{model.model_name}</h3>
                  <Badge tone={model.availability === "mock" ? "amber" : "violet"}>{model.availability === "mock" ? "Development mock" : "Operator configured"}</Badge>
                </div>
                <div className="detail-list">
                  <div><span>Repository</span><strong>{model.repository ?? "Not specified"}</strong></div>
                  <div><span>Version</span><strong>{model.model_version}</strong></div>
                  <div><span>License</span><strong>{model.model_license}</strong></div>
                  <div><span>Commercial use</span><strong>{model.commercial_use_permitted === true ? "Permitted by registry" : model.commercial_use_permitted === false ? "Not permitted until verified" : "Not applicable / not declared"}</strong></div>
                  <div><span>GPU requirement</span><strong>{model.gpu_requirement}</strong></div>
                  <div><span>Modes</span><strong>{model.generation_modes.join(", ")}</strong></div>
                  <div><span>Languages</span><strong>{model.supported_languages.length ? model.supported_languages.join(", ") : "Not specified"}</strong></div>
                </div>
                <p className="workspace-copy">{model.installation_instructions}</p>
              </article>
            ))}
          </Card>
          <Card className="workspace-main-card">
            <SectionHeading title="Independent worker configuration" description="Point the backend to a self-hosted worker; no required paid API is configured." />
            <div className="notice-strip"><Clapperboard size={14} /><span>Configure GENERATION_WORKER_URL and an optional server-side token in the backend environment. Worker API credentials are not exposed to the browser.</span></div>
          </Card>
        </div>
      ) : current === "Storyboard" || current === "Scenes" ? (
        <div className="workspace-main-stack">
          <Card className="workspace-main-card">
            <SectionHeading title="Scene-by-scene storyboard" description="Edit the selected scene's plan and continuity references. Scene generation is requested separately per scene." action={<Button disabled={busy} icon={<Plus size={14} />} onClick={() => void createNewScene()} size="sm">Add scene</Button>} />
            {!scenes.length ? <p className="workspace-copy">No scenes yet. Add a scene to begin a storyboard.</p> : scenes.map((scene, index) => (
              <article className="content-scene-editor" key={scene.id}>
                <div className="content-scene-heading">
                  <span className="content-scene-number">{String(index + 1).padStart(2, "0")}</span>
                  <Badge tone={scene.is_approved ? "green" : "neutral"}>{scene.is_approved ? "Approved" : scene.generation_status.replaceAll("_", " ")}</Badge>
                  {scene.generation_provider ? <Badge>{scene.generation_provider}</Badge> : null}
                  <Button aria-label={`Delete ${scene.title}`} disabled={busy} icon={<Trash2 size={14} />} onClick={() => void run(async () => {
                    await deleteScene(token, projectId, scene.id);
                    setScenes((previous) => previous.filter((item) => item.id !== scene.id));
                  })} size="sm" variant="ghost" />
                </div>
                {scene.generated_preview_label ? <div className="content-preview-label"><Sparkles size={14} />{scene.generated_preview_label}</div> : null}
                <div className="content-scene-fields">
                  <Field label="Scene title"><TextInput onChange={(event) => changeScene(scene.id, { title: event.target.value })} value={scene.title} /></Field>
                  <Field label="Duration (seconds)"><TextInput max="600" min="0.1" onChange={(event) => changeScene(scene.id, { duration_seconds: Number(event.target.value) })} type="number" value={scene.duration_seconds} /></Field>
                  <Field label="Visual style"><SelectInput onChange={(event) => changeScene(scene.id, { visual_style: event.target.value as VisualStyle })} value={scene.visual_style ?? ""}><option value="">Use project default</option>{STYLES.map((style) => <option key={style.value} value={style.value}>{style.label}</option>)}</SelectInput></Field>
                  <Field label="Camera movement"><SelectInput onChange={(event) => changeScene(scene.id, { camera_movement: (event.target.value || null) as CameraMovement | null })} value={scene.camera_movement ?? ""}><option value="">Unspecified</option>{CAMERA_MOVEMENTS.map((camera) => <option key={camera.value} value={camera.value}>{camera.label}</option>)}</SelectInput></Field>
                  <Field label="Environment"><SelectInput onChange={(event) => changeScene(scene.id, { environment_id: event.target.value || null })} value={scene.environment_id ?? ""}><option value="">None selected</option>{environments.map((environment) => <option key={environment.id} value={environment.id}>{environment.name}</option>)}</SelectInput></Field>
                  <Field label="Lighting"><TextInput onChange={(event) => changeScene(scene.id, { lighting: event.target.value })} placeholder="e.g. soft window light" value={scene.lighting ?? ""} /></Field>
                  <Field label="Color palette"><TextInput onChange={(event) => changeScene(scene.id, { color_palette: event.target.value })} placeholder="e.g. cool blue, warm amber" value={scene.color_palette ?? ""} /></Field>
                  <Field label="Characters"><span className="content-character-checks">{characters.map((character) => <label className="content-checkbox" key={character.id}><input checked={scene.character_ids.includes(character.id)} onChange={(event) => changeScene(scene.id, { character_ids: event.target.checked ? [...scene.character_ids, character.id] : scene.character_ids.filter((id) => id !== character.id) })} type="checkbox" />{character.name}</label>)}</span></Field>
                </div>
                <div className="content-generation-options">
                  <Field label="Generation mode">
                    <SelectInput onChange={(event) => setGenerationModes((previous) => ({ ...previous, [scene.id]: event.target.value as "text_to_video" | "image_to_video" }))} value={generationModes[scene.id] ?? "text_to_video"}>
                      <option value="text_to_video">Text-to-video</option>
                      <option value="image_to_video">Image-to-video</option>
                    </SelectInput>
                  </Field>
                  <Field label="Registry model">
                    <SelectInput onChange={(event) => setModelId(event.target.value)} value={modelId}>
                      {models.map((model) => <option disabled={model.availability === "mock" && !provider?.preview_only} key={model.id} value={model.id}>{model.model_name}</option>)}
                    </SelectInput>
                  </Field>
                  <Field label="Output size">
                    <SelectInput onChange={(event) => setResolution(event.target.value)} value={resolution}><option value="1280x720">1280 × 720</option><option value="1920x1080">1920 × 1080</option><option value="720x1280">720 × 1280 vertical</option></SelectInput>
                  </Field>
                  <Field label="Frame rate">
                    <SelectInput onChange={(event) => setFrameRate(event.target.value)} value={frameRate}><option value="24">24 fps</option><option value="30">30 fps</option><option value="60">60 fps</option></SelectInput>
                  </Field>
                </div>
                <Field label="Scene description"><textarea className="text-area" onChange={(event) => changeScene(scene.id, { description: event.target.value })} value={scene.description ?? ""} /></Field>
                <Field label="Scene-specific prompt"><textarea className="text-area" maxLength={20_000} onChange={(event) => changeScene(scene.id, { scene_prompt: event.target.value })} value={scene.scene_prompt ?? ""} /></Field>
                <div className="content-scene-fields">
                  <Field label="First-frame reference"><SelectInput onChange={(event) => changeScene(scene.id, { first_frame_asset_id: event.target.value || null })} value={scene.first_frame_asset_id ?? ""}><option value="">No reference image</option>{images.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}</SelectInput></Field>
                  <Field label="Last-frame reference"><SelectInput onChange={(event) => changeScene(scene.id, { last_frame_asset_id: event.target.value || null })} value={scene.last_frame_asset_id ?? ""}><option value="">No reference image</option>{images.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}</SelectInput></Field>
                  <Field label="Continuity notes"><TextInput onChange={(event) => changeScene(scene.id, { continuity_notes: event.target.value })} value={scene.continuity_notes ?? ""} /></Field>
                </div>
                <div className="content-shot-list">
                  <strong>Shot list · {scene.shots.length}</strong>
                  {scene.shots.map((shot, shotIndex) => <div className="content-shot-row" key={shot.id}>
                    <span>{shotIndex + 1}.</span> {shot.description}
                    <SelectInput aria-label={`Video for shot ${shotIndex + 1}`} onChange={(event) => void run(async () => {
                      const updated = await updateSceneShot(token, projectId, scene.id, shot.id, { media_asset_id: event.target.value || null });
                      setScenes((previous) => previous.map((item) => item.id === scene.id
                        ? { ...item, shots: item.shots.map((entry) => entry.id === updated.id ? updated : entry) }
                        : item));
                    })} value={shot.media_asset_id ?? ""}>
                      <option value="">No video asset</option>
                      {videos.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}
                    </SelectInput>
                  </div>)}
                  {selectedScene?.id === scene.id ? (
                    <div className="content-inline-form">
                      <TextInput aria-label="New shot description" onChange={(event) => setShotDescription(event.target.value)} placeholder="Add a shot description" value={shotDescription} />
                      <SelectInput aria-label="Video asset for new shot" onChange={(event) => setShotVideoId(event.target.value)} value={shotVideoId}><option value="">No video asset</option>{videos.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}</SelectInput>
                      <Button disabled={busy || !shotDescription.trim()} onClick={() => void addShot()} size="sm">Add shot</Button>
                    </div>
                  ) : null}
                </div>
                <div className="content-scene-actions">
                  <Button disabled={busy} icon={<Save size={14} />} onClick={() => void saveScene(scene)} size="sm">Save scene</Button>
                  <Button disabled={busy || !provider?.available || !selectedModel?.generation_modes.includes(generationModes[scene.id] ?? "text_to_video") || !(scene.scene_prompt || scene.description) || (generationModes[scene.id] === "image_to_video" && !scene.first_frame_asset_id)} icon={<RefreshCw size={14} />} onClick={() => void generateScene(scene)} size="sm">Generate this scene</Button>
                  <Button disabled={busy || (!scene.generated_media_asset_id && !scene.shots.some((shot) => shot.media_asset_id))} icon={<Check size={14} />} onClick={() => void run(async () => {
                    const updated = await updateSceneApproval(token, projectId, scene.id, !scene.is_approved);
                    setScenes((previous) => previous.map((item) => item.id === updated.id ? updated : item));
                  })} size="sm" variant={scene.is_approved ? "primary" : "secondary"}>{scene.is_approved ? "Unapprove" : "Approve scene"}</Button>
                </div>
                {!scene.generated_media_asset_id && !scene.shots.some((shot) => shot.media_asset_id) ? <p className="content-hint">Assign a real uploaded video to a shot before approving it for assembly. Mock preview text is never media.</p> : null}
              </article>
            ))}
          </Card>
          <Card className="workspace-main-card">
            <SectionHeading title="Storyboard assembly" description="Create a Video Studio timeline from approved scenes that have real project video assets." />
            <Button disabled={busy || !scenes.some((scene) => scene.is_approved && scene.generated_media_asset_id)} icon={<Clapperboard size={14} />} onClick={() => void assemble()} variant="primary">Assemble approved video scenes</Button>
          </Card>
        </div>
      ) : current === "Character Bible" ? (
        <div className="workspace-main-stack">
          <Card className="workspace-main-card">
            <SectionHeading title="Character Bible" description="Persist identity, visual traits, outfits, and uploaded image references for scene continuity." />
            <div className="content-inline-form"><TextInput aria-label="Character name" onChange={(event) => setNewCharacterName(event.target.value)} placeholder="Character name" value={newCharacterName} /><Button disabled={busy || !newCharacterName.trim()} icon={<Plus size={14} />} onClick={() => void addCharacter()}>Add character</Button></div>
            {characters.map((character) => (
              <article className="content-entity-card" key={character.id}>
                <div className="content-entity-heading"><h3>{character.name}</h3><Button aria-label={`Delete ${character.name}`} disabled={busy} icon={<Trash2 size={14} />} onClick={() => void run(async () => {
                  await deleteCharacter(token, projectId, character.id);
                  setCharacters((previous) => previous.filter((item) => item.id !== character.id));
                })} size="sm" variant="ghost" /></div>
                <Field label="Identity and appearance"><textarea className="text-area" onChange={(event) => setCharacters((previous) => previous.map((item) => item.id === character.id ? { ...item, identity_description: event.target.value } : item))} value={character.identity_description ?? ""} /></Field>
                <div className="content-scene-fields">
                  <Field label="Default outfit"><TextInput onChange={(event) => setCharacters((previous) => previous.map((item) => item.id === character.id ? { ...item, outfit_settings: { ...(item.outfit_settings ?? {}), default: event.target.value } } : item))} value={jsonField(character.outfit_settings, "default")} /></Field>
                  <Field label="Visual traits"><TextInput onChange={(event) => setCharacters((previous) => previous.map((item) => item.id === character.id ? { ...item, visual_traits: { ...(item.visual_traits ?? {}), summary: event.target.value } } : item))} value={jsonField(character.visual_traits, "summary")} /></Field>
                </div>
                <div className="content-inline-form">
                  <SelectInput aria-label={`Reference image for ${character.name}`} onChange={(event) => setReferenceSelections((previous) => ({ ...previous, [character.id]: event.target.value }))} value={referenceSelections[character.id] ?? ""}><option value="">Select an uploaded image</option>{images.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}</SelectInput>
                  <Button disabled={busy || !referenceSelections[character.id]} icon={<ImageIcon size={14} />} onClick={() => void addReference(character.id)} size="sm">Attach character sheet</Button>
                  <Button disabled={busy} onClick={() => void run(async () => {
                    const saved = await updateCharacter(token, projectId, character.id, character);
                    setCharacters((previous) => previous.map((item) => item.id === saved.id ? saved : item));
                    notify("Character details saved.");
                  })} size="sm">Save</Button>
                </div>
                <p className="content-hint">Character references: {(characterRefs[character.id] ?? []).length}. Upload images in Media Library first.</p>
              </article>
            ))}
            {!characters.length ? <p className="workspace-copy">No characters yet.</p> : null}
          </Card>
        </div>
      ) : current === "Environments" ? (
        <div className="workspace-main-stack">
          <Card className="workspace-main-card">
            <SectionHeading title="Environment reference library" description="Keep reusable locations and their visual traits attached to this project." />
            <div className="content-inline-form"><TextInput aria-label="Environment name" onChange={(event) => setNewEnvironmentName(event.target.value)} placeholder="Environment name" value={newEnvironmentName} /><Button disabled={busy || !newEnvironmentName.trim()} icon={<Plus size={14} />} onClick={() => void addEnvironment()}>Add environment</Button></div>
            {environments.map((environment) => (
              <article className="content-entity-card" key={environment.id}>
                <div className="content-entity-heading"><h3>{environment.name}</h3><Button aria-label={`Delete ${environment.name}`} disabled={busy} icon={<Trash2 size={14} />} onClick={() => void run(async () => {
                  await deleteEnvironment(token, projectId, environment.id);
                  setEnvironments((previous) => previous.filter((item) => item.id !== environment.id));
                })} size="sm" variant="ghost" /></div>
                <Field label="Description"><textarea className="text-area" onChange={(event) => setEnvironments((previous) => previous.map((item) => item.id === environment.id ? { ...item, description: event.target.value } : item))} value={environment.description ?? ""} /></Field>
                <div className="content-scene-fields">
                  <Field label="Season"><TextInput onChange={(event) => setEnvironments((previous) => previous.map((item) => item.id === environment.id ? { ...item, visual_traits: { ...(item.visual_traits ?? {}), season: event.target.value } } : item))} value={jsonField(environment.visual_traits, "season")} /></Field>
                  <Field label="Weather / atmosphere"><TextInput onChange={(event) => setEnvironments((previous) => previous.map((item) => item.id === environment.id ? { ...item, visual_traits: { ...(item.visual_traits ?? {}), atmosphere: event.target.value } } : item))} value={jsonField(environment.visual_traits, "atmosphere")} /></Field>
                  <Field label="Reference image"><SelectInput onChange={(event) => setEnvironments((previous) => previous.map((item) => item.id === environment.id ? { ...item, reference_asset_id: event.target.value || null } : item))} value={environment.reference_asset_id ?? ""}><option value="">No image selected</option>{images.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}</SelectInput></Field>
                </div>
                <Button disabled={busy} onClick={() => void run(async () => {
                  const saved = await updateEnvironment(token, projectId, environment.id, environment);
                  setEnvironments((previous) => previous.map((item) => item.id === saved.id ? saved : item));
                  notify("Environment saved.");
                })} size="sm">Save environment</Button>
              </article>
            ))}
            {!environments.length ? <p className="workspace-copy">No environments yet.</p> : null}
          </Card>
        </div>
      ) : current === "Style Guide" ? (
        <div className="workspace-columns content-workspace-columns">
          <Card className="workspace-main-card">
            <SectionHeading title="Visual style and camera language" description="These settings persist on the project and can be overridden scene by scene." />
            <Field label="Visual style"><SelectInput onChange={(event) => updateStyle("visual_style", event.target.value)} value={jsonField(story.visual_settings, "visual_style")}><option value="">Choose style</option>{STYLES.map((style) => <option key={style.value} value={style.value}>{style.label}</option>)}</SelectInput></Field>
            <Field label="Default camera movement"><SelectInput onChange={(event) => updateStyle("camera_movement", event.target.value)} value={jsonField(story.visual_settings, "camera_movement")}><option value="">Choose movement</option>{CAMERA_MOVEMENTS.map((camera) => <option key={camera.value} value={camera.value}>{camera.label}</option>)}</SelectInput></Field>
            <div className="content-scene-fields">
              <Field label="Lighting"><TextInput onChange={(event) => updateStyle("lighting", event.target.value)} value={jsonField(story.visual_settings, "lighting")} /></Field>
              <Field label="Color palette"><TextInput onChange={(event) => updateStyle("color_palette", event.target.value)} value={jsonField(story.visual_settings, "color_palette")} /></Field>
            </div>
            <Button disabled={busy} icon={<Save size={14} />} onClick={() => void saveStory()} variant="primary">Save style guide</Button>
          </Card>
          <Card className="workspace-aside-card"><SectionHeading title="Reference media" description="Use uploaded image assets as scene frame references or attach them to a character or environment." /><p className="workspace-copy">{images.length} uploaded image{images.length === 1 ? "" : "s"} · {videos.length} uploaded video{videos.length === 1 ? "" : "s"} available.</p><div className="notice-strip"><ImageIcon size={14} /><span>Upload reference sheets and environment images in Media Library. No generated visuals are shown as real output.</span></div></Card>
        </div>
      ) : (
        <div className="workspace-main-stack">
          <Card className="workspace-main-card">
            <SectionHeading title="Continuity review" description="Checks persisted scene plans for missing prompts, shots, environment references, and style mismatches." action={<Button disabled={busy} icon={<RefreshCw size={14} />} onClick={() => void reviewContinuity()} size="sm">Run review</Button>} />
            {continuity ? <><div className="content-continuity-summary"><strong>{continuity.issue_count}</strong> planning issue{continuity.issue_count === 1 ? "" : "s"} across {continuity.scenes.length} scenes</div>{continuity.scenes.map((item) => <div className="content-continuity-row" key={item.scene_id}><strong>{item.scene_title}</strong>{item.issues.length ? <ul>{item.issues.map((issue) => <li key={issue}>{issue}</li>)}</ul> : <Badge tone="green">No issues found</Badge>}</div>)}</> : <p className="workspace-copy">Run a continuity review to inspect your saved storyboard.</p>}
          </Card>
          <Card className="workspace-main-card">
            <SectionHeading title="Scene generation availability" description="Generation is separate from project planning and requires an explicitly configured provider." />
            <div className="notice-strip"><Sparkles size={14} /><span>{provider?.available ? `${provider.provider ?? "Provider"} is enabled in preview-only mode.` : "No video generation provider is configured. A self-hosted GPU worker adapter can be connected later."} {provider?.preview_only ? "The mock provider returns text only; it creates no image or video." : ""}</span></div>
            {activeJob ? <p className="content-job-state">Latest job: {activeJob.status} · {activeJob.progress}%{activeJob.error_message ? ` · ${activeJob.error_message}` : ""}</p> : null}
          </Card>
        </div>
      )}
      {busy ? <span className="content-busy-indicator" aria-live="polite">Saving…</span> : null}
    </div>
  );
}
