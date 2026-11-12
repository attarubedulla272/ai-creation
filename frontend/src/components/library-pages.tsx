"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import Image from "next/image";
import {
  AlertCircle,
  AudioLines,
  Check,
  Clock3,
  Download,
  FileAudio,
  FileImage,
  FileVideo2,
  HardDrive,
  Image as ImageIcon,
  LayoutTemplate,
  LogIn,
  MoreHorizontal,
  Plus,
  Search,
  Trash2,
  Upload,
  UserPlus,
} from "lucide-react";
import { demoMedia, demoTemplates } from "@/lib/demo-data";
import { useStudioUI } from "@/components/studio-shell";
import { Badge, Button, Card, Field, SectionHeading, SelectInput, TextInput } from "@/components/ui";
import {
  authenticate,
  deleteMedia,
  downloadMedia,
  getMediaJob,
  listMedia,
  cancelMediaJob,
  loadMediaDerivative,
  loadMediaPreview,
  retryMediaJob,
  type MediaAsset as StoredMediaAsset,
  type MediaJob,
  uploadMedia,
} from "@/lib/media-api";

type MediaFilter = "All media" | "Video" | "Audio" | "Image";

function mediaIcon(type: string) {
  if (type.startsWith("audio") || type === "Audio") return FileAudio;
  if (type.startsWith("image") || type === "Image") return FileImage;
  return FileVideo2;
}

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function MediaThumbnail({
  asset,
  apiBase,
  token,
}: {
  asset: StoredMediaAsset;
  apiBase: string;
  token: string;
}) {
  const [thumbnail, setThumbnail] = useState<{ assetId: string; url: string } | null>(null);
  const [failedAssetId, setFailedAssetId] = useState("");

  useEffect(() => {
    if (!token || !asset.metadata_json?.derivatives?.thumbnail) return;
    let active = true;
    let objectUrl = "";
    void loadMediaDerivative(apiBase, token, asset.id, "thumbnail").then((url) => {
      objectUrl = url;
      if (active) setThumbnail({ assetId: asset.id, url });
      else URL.revokeObjectURL(url);
    }).catch(() => {
      if (active) setFailedAssetId(asset.id);
    });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [apiBase, asset.id, asset.metadata_json, token]);

  const url = thumbnail?.assetId === asset.id ? thumbnail.url : "";
  return url
    ? <Image alt="" className="media-thumbnail" height={42} src={url} unoptimized width={64} />
    : <span aria-label={failedAssetId === asset.id ? "Thumbnail unavailable" : "Thumbnail pending"} className="media-thumbnail-placeholder" />;
}

export function MediaLibraryPage() {
  const { media, removeDemoMedia, notify } = useStudioUI();
  const [filter, setFilter] = useState<MediaFilter>("All media");
  const [query, setQuery] = useState("");
  const [apiBase, setApiBase] = useState("http://localhost:8000");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [createAccount, setCreateAccount] = useState(false);
  const [assets, setAssets] = useState<StoredMediaAsset[]>([]);
  const [jobs, setJobs] = useState<(MediaJob & { assetId: string; filename: string })[]>([]);
  const [uploading, setUploading] = useState<{ filename: string; progress: number } | null>(null);
  const [apiError, setApiError] = useState("");
  const [loadingAssets, setLoadingAssets] = useState(false);
  const [previewAssetId, setPreviewAssetId] = useState("");
  const [previewUrl, setPreviewUrl] = useState("");
  const [previewError, setPreviewError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const jobsRef = useRef(jobs);
  useEffect(() => {
    jobsRef.current = jobs;
  }, [jobs]);
  const activeJobs = useMemo(
    () => jobs.filter((job) => job.status === "queued" || job.status === "processing"),
    [jobs],
  );
  const previewAsset = assets.find((asset) => asset.id === previewAssetId);
  const filteredAssets = assets.filter((asset) =>
    (filter === "All media" || asset.media_type === filter.toLowerCase())
    && asset.name.toLowerCase().includes(query.toLowerCase()));
  const filteredSamples = demoMedia.filter((item) =>
    (filter === "All media" || item.type === filter)
    && item.name.toLowerCase().includes(query.toLowerCase()));
  const filteredLocal = media.filter((item) =>
    (filter === "All media"
      || (filter === "Video" && item.type.startsWith("video/"))
      || (filter === "Audio" && item.type.startsWith("audio/"))
      || (filter === "Image" && item.type.startsWith("image/")))
    && item.name.toLowerCase().includes(query.toLowerCase()));

  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (active) setToken(window.sessionStorage.getItem("ai-creator-studio:media-token") ?? "");
    });
    return () => {
      active = false;
    };
  }, []);

  const refreshAssets = useCallback(async () => {
    if (!token) return;
    setLoadingAssets(true);
    try {
      const currentAssets = await listMedia(apiBase, token);
      setAssets(currentAssets);
      const savedJobs = await Promise.all(currentAssets.flatMap((asset) => {
        const jobId = asset.metadata_json?.processing_job_id;
        if (!jobId || jobsRef.current.some((job) => job.id === jobId)) return [];
        return [getMediaJob(apiBase, token, jobId).then((job) => ({
          ...job,
          assetId: asset.id,
          filename: asset.name,
        }))];
      }));
      if (savedJobs.length) {
        setJobs((current) => [...current, ...savedJobs.filter((job) => !current.some((item) => item.id === job.id))]);
      }
      setApiError("");
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Could not load media from the backend.");
    } finally {
      setLoadingAssets(false);
    }
  }, [apiBase, token]);

  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (active && token) void refreshAssets();
    });
    return () => {
      active = false;
    };
  }, [refreshAssets, token]);

  useEffect(() => {
    if (!token || !previewAsset) return;
    let active = true;
    let objectUrl = "";
    const preview = previewAsset.metadata_json?.derivatives?.proxy
      ? loadMediaDerivative(apiBase, token, previewAsset.id, "proxy")
      : loadMediaPreview(apiBase, token, previewAsset.id);
    void preview.then((url) => {
      objectUrl = url;
      if (active) setPreviewUrl(url);
      else URL.revokeObjectURL(url);
    }).catch((error: unknown) => {
      if (active) setPreviewError(error instanceof Error ? error.message : "Could not preview media.");
    });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [apiBase, previewAsset, token]);

  useEffect(() => {
    if (!token || !activeJobs.length) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      const updates = await Promise.all(activeJobs.map(async (job) => {
        try {
          return { ...job, ...await getMediaJob(apiBase, token, job.id) };
        } catch (error) {
          return {
            ...job,
            status: "failed" as const,
            error_message: error instanceof Error ? error.message : "Could not read processing status.",
          };
        }
      }));
      if (!active) return;
      setJobs((current) => {
        let changed = false;
        const next = current.map((job) => {
          const update = updates.find((item) => item.id === job.id);
          if (!update || (job.status === update.status
            && job.progress === update.progress
            && job.error_message === update.error_message
            && job.cancellation_requested === update.cancellation_requested
            && job.retry_count === update.retry_count)) return job;
          changed = true;
          return { ...job, ...update };
        });
        return changed ? next : current;
      });
      if (updates.some((job) => job.status === "completed")) void refreshAssets();
      if (updates.some((job) => job.status === "failed")) {
        const failed = updates.find((job) => job.status === "failed");
        if (failed?.error_message) setApiError(failed.error_message);
      }
      if (updates.some((job) => job.status === "queued" || job.status === "processing")) {
        timer = setTimeout(poll, 900);
      }
    };
    timer = setTimeout(poll, 500);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [activeJobs, apiBase, refreshAssets, token]);

  async function connectAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAuthBusy(true);
    setApiError("");
    try {
      const accessToken = await authenticate(apiBase, email, password, createAccount);
      window.sessionStorage.setItem("ai-creator-studio:media-token", accessToken);
      setToken(accessToken);
      setPassword("");
      notify(createAccount ? "Account created and connected." : "Connected to the media backend.");
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Could not connect to the media backend.");
    } finally {
      setAuthBusy(false);
    }
  }

  function disconnectAccount() {
    window.sessionStorage.removeItem("ai-creator-studio:media-token");
    setToken("");
    setAssets([]);
    setJobs([]);
    setApiError("");
  }

  async function uploadSelectedFiles(files: FileList | null) {
    if (!files || !token) return;
    setApiError("");
    for (const file of Array.from(files)) {
      setUploading({ filename: file.name, progress: 0 });
      try {
        const result = await uploadMedia(apiBase, token, file, (progress) => {
          setUploading({ filename: file.name, progress });
        });
        setJobs((current) => [
          ...current,
          {
            id: result.job_id,
            assetId: result.asset.id,
            filename: result.asset.name,
            job_type: "media_process",
            status: "queued",
            progress: 0,
            error_message: null,
            retry_count: 0,
            max_retries: 2,
            cancellation_requested: false,
          },
        ]);
        await refreshAssets();
      } catch (error) {
        setApiError(error instanceof Error ? error.message : `Could not upload ${file.name}.`);
        break;
      } finally {
        setUploading(null);
      }
    }
    if (fileInput.current) fileInput.current.value = "";
  }

  async function removeAsset(asset: StoredMediaAsset) {
    if (!token || !window.confirm(`Delete “${asset.name}” and its generated files?`)) return;
    try {
      await deleteMedia(apiBase, token, asset.id);
      setAssets((current) => current.filter((item) => item.id !== asset.id));
      notify("Media asset deleted.");
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Could not delete the media asset.");
    }
  }

  async function downloadAsset(asset: StoredMediaAsset, derivative?: string) {
    if (!token) return;
    try {
      await downloadMedia(apiBase, token, asset.id, derivative);
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Could not download the media file.");
    }
  }

  async function updateMediaJob(job: MediaJob & { assetId: string; filename: string }, action: "retry" | "cancel") {
    if (!token) return;
    try {
      const updated = action === "retry"
        ? await retryMediaJob(apiBase, token, job.id)
        : await cancelMediaJob(apiBase, token, job.id);
      setJobs((current) => current.map((item) =>
        item.id === job.id ? { ...item, ...updated } : item));
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Could not update the media processing job.");
    }
  }

  function togglePreview(asset: StoredMediaAsset) {
    setPreviewError("");
    setPreviewUrl("");
    setPreviewAssetId((current) => current === asset.id ? "" : asset.id);
  }

  const storedBytes = assets.reduce((total, asset) => total + asset.file_size, 0);

  return (
    <div className="page-container">
      <div className="page-heading-row">
        <div>
          <div className="eyebrow">YOUR ASSET LIBRARY</div>
          <h1>Media library</h1>
          <p>Upload and organize media in your local backend storage.</p>
        </div>
        <Button
          disabled={!token || Boolean(uploading)}
          icon={<Upload size={15} />}
          onClick={() => fileInput.current?.click()}
          variant="primary"
        >
          Upload media
        </Button>
        <input
          accept="video/mp4,video/quicktime,video/x-matroska,video/webm,video/x-msvideo,audio/mpeg,audio/wav,audio/mp4,audio/aac,audio/ogg,audio/flac,image/png,image/jpeg,image/webp,image/gif,.mp4,.m4v,.mov,.mkv,.webm,.avi,.mp3,.wav,.m4a,.aac,.ogg,.flac,.png,.jpg,.jpeg,.webp,.gif"
          className="visually-hidden"
          multiple
          onChange={(event) => void uploadSelectedFiles(event.target.files)}
          ref={fileInput}
          type="file"
        />
      </div>
      <div className="media-stat-row">
        <Card><HardDrive size={17} /><span><strong>{token ? formatBytes(storedBytes) : "—"}</strong><small>Backend asset storage</small></span><Badge tone={token ? "green" : "neutral"}>{token ? "Connected" : "Offline"}</Badge></Card>
        <Card><FileVideo2 size={17} /><span><strong>{token ? assets.filter((asset) => asset.media_type === "video").length : "—"}</strong><small>Video files</small></span></Card>
        <Card><AudioLines size={17} /><span><strong>{token ? assets.filter((asset) => asset.media_type === "audio").length : "—"}</strong><small>Audio files</small></span></Card>
      </div>
      <Card className="media-backend-card">
        <div className="media-backend-heading">
          <div><strong>Local media backend</strong><small>Files remain on your configured server; no third-party media APIs are used.</small></div>
          {token ? <Button onClick={disconnectAccount} size="sm" variant="ghost">Disconnect</Button> : null}
        </div>
        {token ? (
          <div className="media-connection-state"><Check size={15} /> Connected to {apiBase}</div>
        ) : (
          <form className="media-backend-form" onSubmit={(event) => void connectAccount(event)}>
            <Field label="Backend URL">
              <TextInput autoComplete="url" onChange={(event) => setApiBase(event.target.value)} value={apiBase} />
            </Field>
            <Field label="Email">
              <TextInput autoComplete="email" onChange={(event) => setEmail(event.target.value)} required type="email" value={email} />
            </Field>
            <Field label="Password">
              <TextInput autoComplete={createAccount ? "new-password" : "current-password"} minLength={createAccount ? 12 : undefined} onChange={(event) => setPassword(event.target.value)} required type="password" value={password} />
            </Field>
            <div className="media-auth-actions">
              <Button disabled={authBusy} icon={createAccount ? <UserPlus size={14} /> : <LogIn size={14} />} type="submit" variant="primary">
                {authBusy ? "Connecting…" : createAccount ? "Create account" : "Sign in"}
              </Button>
              <button className="text-button" onClick={() => setCreateAccount((value) => !value)} type="button">
                {createAccount ? "I already have an account" : "Create a local account"}
              </button>
            </div>
          </form>
        )}
        {apiError ? <p className="media-api-error" role="alert"><AlertCircle size={14} />{apiError}</p> : null}
        {uploading ? (
          <div aria-live="polite" className="media-upload-progress">
            <div><span>Uploading {uploading.filename}</span><strong>{uploading.progress}%</strong></div>
            <progress max={100} value={uploading.progress} />
          </div>
        ) : null}
        {jobs.filter((job) => job.status === "queued" || job.status === "processing").map((job) => (
          <div aria-live="polite" className="media-upload-progress" key={job.id}>
            <div><span><Clock3 size={13} /> Processing {job.filename}</span><strong>{job.progress}%</strong></div>
            <progress max={100} value={job.progress} />
          </div>
        ))}
      </Card>
      <div className="library-toolbar">
        <div className="filter-tabs" aria-label="Filter media">
          {(["All media", "Video", "Audio", "Image"] as const).map((item) => (
            <button
              aria-pressed={filter === item}
              className={filter === item ? "filter-tab filter-tab-active" : "filter-tab"}
              key={item}
              onClick={() => setFilter(item)}
              type="button"
            >
              {item}
            </button>
          ))}
        </div>
        <label className="inline-search">
          <Search size={15} />
          <input onChange={(event) => setQuery(event.target.value)} placeholder="Search media" value={query} />
        </label>
      </div>
      <section className="section-block">
        <SectionHeading
          action={token ? <Badge tone="green">Server storage</Badge> : <Badge>Sign in to connect</Badge>}
          description="Uploaded media and FFmpeg processing results stored on your backend."
          title="Your media"
        />
        {loadingAssets ? <p className="media-loading">Loading your media…</p> : null}
        {filteredAssets.length ? (
          <div className="media-list">
            {filteredAssets.map((asset) => {
              const Icon = mediaIcon(asset.media_type);
              const job = jobs.find((item) => item.assetId === asset.id);
              const probe = asset.metadata_json?.probe;
              return (
                <Card className="media-row" key={asset.id}>
                  <span className="media-icon media-icon-local"><Icon size={18} /></span>
                  <MediaThumbnail apiBase={apiBase} asset={asset} token={token} />
                  <span className="media-info">
                    <strong>{asset.name}</strong>
                    <small>
                      {[
                        asset.content_type,
                        probe?.width && probe.height ? `${probe.width}×${probe.height}` : null,
                        probe?.frame_rate ? `${probe.frame_rate.toFixed(1)} fps` : null,
                        probe?.video_codec ?? probe?.audio_streams?.[0]?.codec ?? null,
                        asset.duration_seconds ? `${asset.duration_seconds.toFixed(1)} sec` : null,
                      ].filter(Boolean).join(" · ") || "Analyzing media"}
                    </small>
                  </span>
                  <span className="media-size">{formatBytes(asset.file_size)}</span>
                  {job && (job.status === "queued" || job.status === "processing")
                    ? <Badge tone="violet">{job.status} · {job.progress}%</Badge>
                    : job?.status === "failed"
                      ? <Badge tone="amber">Processing failed</Badge>
                      : job?.status === "cancelled"
                        ? <Badge tone="amber">Cancelled</Badge>
                      : job?.status === "completed"
                        ? <Badge tone="green">Ready</Badge>
                        : <Badge>Stored</Badge>}
                  {asset.media_type === "video" ? (
                    <button className="text-button" onClick={() => togglePreview(asset)} type="button">
                      {previewAssetId === asset.id ? "Close preview" : "Preview"}
                    </button>
                  ) : null}
                  <button aria-label={`Download ${asset.name}`} className="icon-button" onClick={() => void downloadAsset(asset)} type="button"><Download size={15} /></button>
                  <button aria-label={`Delete ${asset.name}`} className="icon-button" onClick={() => void removeAsset(asset)} type="button"><Trash2 size={15} /></button>
                  {job?.status === "failed" && job.error_message ? <small className="media-job-error">{job.error_message}</small> : null}
                  {job?.cancellation_requested ? <small className="media-job-error">Cancellation requested…</small> : null}
                  {job && (job.status === "queued" || job.status === "processing") ? (
                    <button className="text-button" onClick={() => void updateMediaJob(job, "cancel")} type="button">Cancel processing</button>
                  ) : null}
                  {job && (job.status === "failed" || job.status === "cancelled")
                    && job.retry_count < job.max_retries ? (
                      <button className="text-button" onClick={() => void updateMediaJob(job, "retry")} type="button">Retry processing</button>
                    ) : null}
                  {previewAssetId === asset.id ? (
                    <div className="media-preview">
                      {previewError ? <small className="media-job-error" role="alert">{previewError}</small> : null}
                      {previewUrl ? <video aria-label={`Preview ${asset.name}`} controls preload="metadata" src={previewUrl} /> : null}
                    </div>
                  ) : null}
                  {job?.status === "completed" ? (
                    <div className="media-derivatives">
                      {Object.keys(asset.metadata_json?.derivatives ?? {}).map((kind) => (
                        <button className="text-button" key={kind} onClick={() => void downloadAsset(asset, kind)} type="button">
                          Download {kind.replaceAll("_", " ")}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </Card>
              );
            })}
          </div>
        ) : !loadingAssets ? (
          <Card className="empty-state"><ImageIcon size={20} /><strong>{token ? "No uploaded media yet" : "Connect your backend account"}</strong><span>{token ? "Upload a video, audio file, or image to get started." : "Sign in above to upload and manage server-stored assets."}</span></Card>
        ) : null}
      </section>
      {filteredLocal.length ? (
        <section className="section-block">
          <SectionHeading
            action={<Badge tone="violet">Stored in this browser</Badge>}
            description="Only file metadata is stored. The selected files were not uploaded."
            title="Local selections"
          />
          <div className="media-list">
            {filteredLocal.map((item) => {
              const Icon = mediaIcon(item.type);
              return (
                <Card className="media-row" key={item.id}>
                  <span className="media-icon media-icon-local"><Icon size={18} /></span>
                  <span className="media-info"><strong>{item.name}</strong><small>{item.type || "Unknown media"} · Added locally</small></span>
                  <span className="media-size">{formatBytes(item.size)}</span>
                  <Badge tone="violet">Not uploaded</Badge>
                  <button
                    aria-label={`Remove ${item.name} from local demo library`}
                    className="icon-button"
                    onClick={() => removeDemoMedia(item.id)}
                    type="button"
                  >
                    <Trash2 size={15} />
                  </button>
                </Card>
              );
            })}
          </div>
        </section>
      ) : null}
      <section className="section-block">
        <SectionHeading
          action={<Badge>Sample data</Badge>}
          description="Illustrative examples only. These files are not present in your storage."
          title="Example assets"
        />
        {filteredSamples.length ? (
          <div className="media-list">
            {filteredSamples.map((item) => {
              const Icon = mediaIcon(item.type);
              return (
                <Card className="media-row" key={item.name}>
                  <span className="media-icon"><Icon size={18} /></span>
                  <span className="media-info"><strong>{item.name}</strong><small>{item.type} · Demonstration asset</small></span>
                  <span className="media-duration">{item.duration}</span>
                  <span className="media-size">{item.size}</span>
                  <Badge>Demo</Badge>
                  <button aria-label={`More options for ${item.name}`} className="icon-button" type="button"><MoreHorizontal size={16} /></button>
                </Card>
              );
            })}
          </div>
        ) : (
          <Card className="empty-state"><ImageIcon size={20} /><strong>No matching media</strong><span>Try another search or media type.</span></Card>
        )}
      </section>
      <div className="notice-strip"><HardDrive size={15} /><span>Browser selections and example assets below are demonstrations only. Server uploads are validated and processed locally with FFmpeg.</span></div>
    </div>
  );
}

export function TemplatesPage() {
  const { saveDemoProject } = useStudioUI();

  return (
    <div className="page-container">
      <div className="page-heading-row">
        <div>
          <div className="eyebrow">START WITH A STRUCTURE</div>
          <h1>Templates</h1>
          <p>Use a sample outline to create a local project draft.</p>
        </div>
        <Badge>Demonstration templates</Badge>
      </div>
      <div className="template-feature">
        <span className="template-feature-icon"><LayoutTemplate size={24} /></span>
        <div><Badge tone="violet">CREATOR TOOLKIT</Badge><h2>A thoughtful starting point.</h2><p>These are lightweight project outlines, not prebuilt edits or generated media.</p></div>
      </div>
      <section className="section-block">
        <SectionHeading title="Explore templates" description="Choose a format that fits your next story." />
        <div className="template-grid">
          {demoTemplates.map((template, index) => (
            <Card className="template-card" key={template.title}>
              <div className={`template-cover template-${template.color}`}>
                <span className="template-frame"><span /><span /><span /></span>
                <Badge>Demo outline</Badge>
              </div>
              <div className="template-card-body">
                <div className="template-card-meta"><span>{template.type}</span><span>{template.duration}</span></div>
                <h3>{template.title}</h3>
                <p>{index === 0 ? "A clear introduction, one central idea, and an easy next step." : index === 1 ? "A simple opening, three story beats, and a reflective close." : index === 2 ? "Introduce a need, show the experience, and close with a point of view." : "A conversation outline with space for moments, context, and captions."}</p>
                <Button
                  className="template-use-button"
                  icon={<Plus size={14} />}
                  onClick={() => saveDemoProject(template.title, `${template.type} · Template draft`)}
                  size="sm"
                >
                  Use outline
                </Button>
              </div>
            </Card>
          ))}
        </div>
      </section>
    </div>
  );
}

const preferenceKey = "ai-creator-studio:preferences";

type Preferences = {
  projectFormat: string;
  emailUpdates: boolean;
  compactCards: boolean;
};

const defaultPreferences: Preferences = {
  projectFormat: "16:9 Landscape",
  emailUpdates: false,
  compactCards: false,
};

export function SettingsPage() {
  const { notify } = useStudioUI();
  const [preferences, setPreferences] = useState(defaultPreferences);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      try {
        const stored = window.localStorage.getItem(preferenceKey);
        if (!stored) return;
        const parsed = JSON.parse(stored) as Partial<Preferences>;
        setPreferences({
          projectFormat: typeof parsed.projectFormat === "string"
            ? parsed.projectFormat
            : defaultPreferences.projectFormat,
          emailUpdates: typeof parsed.emailUpdates === "boolean"
            ? parsed.emailUpdates
            : defaultPreferences.emailUpdates,
          compactCards: typeof parsed.compactCards === "boolean"
            ? parsed.compactCards
            : defaultPreferences.compactCards,
        });
      } catch {
        notify("Saved preferences could not be read from browser storage.", "error");
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [notify]);

  function update<K extends keyof Preferences>(key: K, value: Preferences[K]) {
    setPreferences((current) => ({ ...current, [key]: value }));
    setSaved(false);
  }

  function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      window.localStorage.setItem(preferenceKey, JSON.stringify(preferences));
      setSaved(true);
      notify("Demo preferences saved in this browser.");
    } catch {
      notify("Could not save preferences in browser storage.", "error");
    }
  }

  return (
    <div className="page-container">
      <div className="page-heading-row">
        <div>
          <div className="eyebrow">MAKE IT YOURS</div>
          <h1>Settings</h1>
          <p>Preferences for this browser-based studio foundation.</p>
        </div>
        <Badge tone="violet">Local demo settings</Badge>
      </div>
      <div className="settings-layout">
        <nav aria-label="Settings sections" className="settings-nav">
          <a className="settings-nav-active" href="#profile">Profile</a>
          <a href="#preferences">Preferences</a>
          <a href="#storage-settings">Storage</a>
          <a href="#privacy">Privacy & data</a>
        </nav>
        <div className="settings-content">
          <Card className="settings-card" id="profile">
            <SectionHeading title="Profile" description="Account details are illustrative and are not connected to authentication." />
            <div className="settings-profile">
              <span className="profile-avatar settings-avatar">A</span>
              <div><strong>Alex Morgan</strong><small>Demo account · Sign-in is not implemented</small></div>
              <Badge>Example</Badge>
            </div>
            <div className="settings-field-grid">
              <Field label="Display name"><TextInput defaultValue="Alex Morgan" disabled /></Field>
              <Field label="Email address"><TextInput defaultValue="alex@example.test" disabled /></Field>
            </div>
          </Card>

          <form onSubmit={handleSave}>
            <Card className="settings-card" id="preferences">
              <SectionHeading title="Workspace preferences" description="Saved locally in this browser. These do not change AI or export behavior." />
              <Field label="Default project format">
                <SelectInput onChange={(event) => update("projectFormat", event.target.value)} value={preferences.projectFormat}>
                  <option>16:9 Landscape</option>
                  <option>9:16 Portrait</option>
                  <option>1:1 Square</option>
                </SelectInput>
              </Field>
              <label className="preference-toggle">
                <span><strong>Product updates</strong><small>Email delivery is not connected.</small></span>
                <input checked={preferences.emailUpdates} onChange={(event) => update("emailUpdates", event.target.checked)} type="checkbox" />
              </label>
              <label className="preference-toggle">
                <span><strong>Compact project cards</strong><small>Demo preference; no other page styling changes yet.</small></span>
                <input checked={preferences.compactCards} onChange={(event) => update("compactCards", event.target.checked)} type="checkbox" />
              </label>
              <div className="settings-save-row">
                {saved ? <span className="saved-state"><Check size={14} /> Saved in this browser</span> : <span className="field-hint">Local preferences only</span>}
                <Button type="submit" variant="primary">Save preferences</Button>
              </div>
            </Card>
          </form>

          <Card className="settings-card" id="storage-settings">
            <SectionHeading title="Storage" description="Your browser holds only project drafts and media metadata created in this demo." />
            <div className="settings-storage-callout"><HardDrive size={18} /><span><strong>No server storage connected</strong><small>There is no cloud sync, backend asset storage, or account-level usage tracking.</small></span></div>
          </Card>

          <Card className="settings-card" id="privacy">
            <SectionHeading title="Privacy & data" description="No third-party AI provider or publishing integration is active." />
            <div className="settings-privacy-grid">
              <div><Badge tone="green">Local</Badge><strong>Drafts stay in this browser</strong><small>Browser storage only, unless you clear it.</small></div>
              <div><Badge>Not connected</Badge><strong>AI and social accounts</strong><small>No AI processing or publishing happens here.</small></div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
