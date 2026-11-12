"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  Check,
  Download,
  FileVideo2,
  LoaderCircle,
  Play,
  RefreshCw,
  Scissors,
  ShieldCheck,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import { Badge, Button, Card, Field, SectionHeading, SelectInput, TextInput } from "@/components/ui";
import { useStudioUI } from "@/components/studio-shell";
import { authenticate, listMedia, uploadMedia, type MediaAsset } from "@/lib/media-api";
import { listStudioProjects, loadMediaPreview, type StudioProject } from "@/lib/timeline-api";
import {
  cancelClipJob,
  createClipAnalysis,
  createClipExport,
  downloadClipCaptions,
  getClipperCapabilities,
  getClipJob,
  listClipCandidates,
  rankClipCandidates,
  retryClipJob,
  setClipCandidateStatus,
  updateClipCandidate,
  updateClipCaptions,
  updateClipFraming,
  type ClipCandidate,
  type ClipCaption,
  type ClipExportInput,
  type ClipJob,
  type ClipRankPreferences,
} from "@/lib/clipper-api";

const TOKEN_KEY = "ai-creator-studio:media-token";
const factorLabels: Record<string, string> = {
  scene_changes: "Scene changes",
  speech_activity: "Speech activity",
  silence_boundaries: "Silence boundaries",
  sentence_completeness: "Sentence completeness",
  beginning_quality: "Beginning quality",
  ending_quality: "Ending quality",
  interesting_opening: "Interesting opening",
  question_or_answer: "Question or answer",
  key_insight: "Key insight",
  emotional_language: "Emotional language",
  standalone_thought: "Complete thought",
  pacing: "Pacing",
};
const defaultRanking: ClipRankPreferences = {
  scene_changes: 0.8,
  speech_activity: 1,
  silence_boundaries: 0.8,
  sentence_completeness: 1.2,
  beginning_quality: 1,
  ending_quality: 1,
  interesting_opening: 1.4,
  question_or_answer: 1.2,
  key_insight: 1.3,
  emotional_language: 0.8,
  standalone_thought: 1.2,
  pacing: 1,
};

function timecode(seconds: number) {
  const mins = Math.floor(seconds / 60).toString().padStart(2, "0");
  return `${mins}:${Math.floor(seconds % 60).toString().padStart(2, "0")}`;
}

function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function candidateTitle(candidate: ClipCandidate) {
  return candidate.title || candidate.transcript_text?.trim().slice(0, 68) || "Transcript highlight";
}

function ConnectForm({
  apiBase,
  setApiBase,
  onConnected,
}: {
  apiBase: string;
  setApiBase: (value: string) => void;
  onConnected: (token: string) => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [newAccount, setNewAccount] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const token = await authenticate(apiBase, email, password, newAccount);
      window.sessionStorage.setItem(TOKEN_KEY, token);
      onConnected(token);
      setPassword("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not connect to the backend.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="workspace-main-card clipper-connect">
      <SectionHeading title="Connect your local workspace" description="Sign in to load your own project videos and analysis. No demonstration clips are shown as generated results." />
      <form className="clipper-connect-form" onSubmit={(event) => void submit(event)}>
        <Field label="API address"><TextInput onChange={(event) => setApiBase(event.target.value)} value={apiBase} /></Field>
        <Field label="Email"><TextInput autoComplete="email" onChange={(event) => setEmail(event.target.value)} required type="email" value={email} /></Field>
        <Field label="Password"><TextInput autoComplete={newAccount ? "new-password" : "current-password"} onChange={(event) => setPassword(event.target.value)} required type="password" value={password} /></Field>
        <label className="clipper-checkbox"><input checked={newAccount} onChange={(event) => setNewAccount(event.target.checked)} type="checkbox" /> Create a new account</label>
        {error ? <p className="error-message" role="alert">{error}</p> : null}
        <Button disabled={busy} icon={busy ? <LoaderCircle className="spin" size={15} /> : <ShieldCheck size={15} />} type="submit" variant="primary">Connect</Button>
      </form>
    </Card>
  );
}

export function SmartClipperWorkspace({ current }: { current: string }) {
  const { notify } = useStudioUI();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [apiBase, setApiBase] = useState("http://localhost:8000");
  const [token, setToken] = useState("");
  const [projects, setProjects] = useState<StudioProject[]>([]);
  const [assets, setAssets] = useState<MediaAsset[]>([]);
  const [projectId, setProjectId] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [candidates, setCandidates] = useState<ClipCandidate[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [job, setJob] = useState<ClipJob | null>(null);
  const [preview, setPreview] = useState<{ assetId: string; url: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [minimum, setMinimum] = useState(15);
  const [maximum, setMaximum] = useState(60);
  const [targetDurations, setTargetDurations] = useState<Array<15 | 30 | 45 | 60>>([15, 30, 45, 60]);
  const [editStart, setEditStart] = useState(0);
  const [editEnd, setEditEnd] = useState(0);
  const [captionDraft, setCaptionDraft] = useState<ClipCaption[]>([]);
  const [aspectRatio, setAspectRatio] = useState<ClipExportInput["aspect_ratio"]>("9:16");
  const [resolution, setResolution] = useState<ClipExportInput["resolution"]>("1080p");
  const [captionsEnabled, setCaptionsEnabled] = useState(true);
  const [captionPosition, setCaptionPosition] = useState<ClipExportInput["caption_position"]>("bottom");
  const [captionFontSize, setCaptionFontSize] = useState(36);
  const [captionColor, setCaptionColor] = useState("#FFFFFF");
  const [captionTheme, setCaptionTheme] = useState<ClipExportInput["caption_theme"]>("boxed");
  const [captionBackgroundColor, setCaptionBackgroundColor] = useState("#000000");
  const [captionOutlineColor, setCaptionOutlineColor] = useState("#000000");
  const [watermark, setWatermark] = useState("");
  const [selectedForExport, setSelectedForExport] = useState<string[]>([]);
  const [framingX, setFramingX] = useState(0.5);
  const [framingY, setFramingY] = useState(0.5);
  const [bRoll, setBRoll] = useState<{ id: string; name: string; matched_terms: string[]; reason: string }[]>([]);
  const [capabilities, setCapabilities] = useState<Awaited<ReturnType<typeof getClipperCapabilities>> | null>(null);
  const [rankingPreferences, setRankingPreferences] = useState(defaultRanking);
  const [uploadProgress, setUploadProgress] = useState(0);

  const selectedProject = projects.find((project) => project.id === projectId) ?? null;
  const projectVideos = useMemo(
    () => assets.filter((asset) => asset.media_type === "video" && asset.project_id === projectId),
    [assets, projectId],
  );
  const source = projectVideos.find((asset) => asset.id === sourceId) ?? null;
  const selectedCandidate = candidates.find((candidate) => candidate.id === selectedId) ?? null;
  const activePreviewAssetId = selectedCandidate?.exported_media_asset_id
    ?? selectedCandidate?.source_asset_id
    ?? sourceId;
  const previewUrl = preview?.assetId === activePreviewAssetId ? preview.url : "";
  const approved = candidates.filter((candidate) => candidate.status === "approved");
  const analyzedScenes = Array.isArray(job?.output_data?.scene_changes)
    ? job.output_data.scene_changes as Array<{ start_seconds: number; end_seconds: number }>
    : [];
  const analyzedSilences = Array.isArray(job?.output_data?.silence_ranges)
    ? job.output_data.silence_ranges as Array<{ start_seconds: number; end_seconds: number }>
    : [];
  const analysisProbe = job?.output_data?.probe;
  const analysisDuration = analysisProbe && typeof analysisProbe === "object"
    && "duration_seconds" in analysisProbe
    && typeof analysisProbe.duration_seconds === "number"
    ? analysisProbe.duration_seconds
    : undefined;
  const sourceDuration = source?.duration_seconds ?? analysisDuration;

  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (active) setToken(window.sessionStorage.getItem(TOKEN_KEY) ?? "");
    });
    return () => { active = false; };
  }, []);

  const refresh = useCallback(async () => {
    if (!token) return;
    const [projectItems, mediaItems] = await Promise.all([
      listStudioProjects(apiBase, token),
      listMedia(apiBase, token),
    ]);
    setProjects(projectItems);
    setAssets(mediaItems);
    setProjectId((currentId) => projectItems.some((item) => item.id === currentId)
      ? currentId : projectItems[0]?.id ?? "");
    setError("");
  }, [apiBase, token]);

  useEffect(() => {
    if (!token) return;
    let active = true;
    void Promise.resolve().then(() => active ? refresh() : undefined).catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Could not load projects and media.");
      });
    return () => { active = false; };
  }, [refresh, token]);

  useEffect(() => {
    if (!token) return;
    let active = true;
    void getClipperCapabilities(apiBase, token).then((value) => {
      if (active) setCapabilities(value);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Could not read processing capabilities.");
    });
    return () => { active = false; };
  }, [apiBase, token]);

  useEffect(() => {
    if (!projectId || !token) return;
    let active = true;
    void listClipCandidates(apiBase, token, projectId).then((items) => {
      if (!active) return;
      setCandidates(items);
      if (items[0]) chooseCandidate(items[0]);
      else setSelectedId("");
      setSelectedForExport((ids) => ids.filter((id) => items.some((candidate) => candidate.id === id && candidate.status === "approved")));
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Could not load clip candidates.");
    });
    return () => { active = false; };
  }, [apiBase, projectId, token]);

  useEffect(() => {
    const activeMediaId = selectedCandidate?.exported_media_asset_id
      ?? selectedCandidate?.source_asset_id
      ?? sourceId;
    if (!token || !activeMediaId) return;
    let active = true;
    let objectUrl = "";
    void loadMediaPreview(apiBase, token, activeMediaId).then((url) => {
      objectUrl = url;
      if (active) setPreview({ assetId: activeMediaId, url });
      else URL.revokeObjectURL(url);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Could not load video preview.");
    });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [apiBase, selectedCandidate?.exported_media_asset_id, selectedCandidate?.source_asset_id, sourceId, token]);

  useEffect(() => {
    if (!job || ["completed", "failed", "cancelled"].includes(job.status) || !token) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const latest = await getClipJob(apiBase, token, job.id);
        if (!active) return;
        setJob(latest);
        if (latest.status === "completed") {
          if (latest.job_type === "smart_clip_analysis" && latest.project_id) {
            const analyzedCandidates = await listClipCandidates(apiBase, token, latest.project_id);
            setCandidates(analyzedCandidates);
            if (analyzedCandidates[0]) chooseCandidate(analyzedCandidates[0]);
            else setSelectedId("");
            notify(`Analysis complete. ${String(latest.output_data?.candidate_count ?? 0)} transcript-based candidates are ready.`);
          } else if (latest.job_type === "smart_clip_export") {
            const ids = await listClipCandidates(apiBase, token, projectId);
            setCandidates(ids);
            setSelectedForExport((currentIds) => currentIds.filter((id) => ids.some((item) => item.id === id && item.status === "approved")));
            notify("Batch export completed and saved clips to the project media library.");
          }
        } else if (latest.status === "failed") {
          setError(latest.error_message ?? "Smart Clipper job failed.");
        } else if (latest.status !== "cancelled") {
          timer = setTimeout(poll, 800);
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Could not refresh job progress.");
      }
    };
    timer = setTimeout(poll, 500);
    return () => { active = false; clearTimeout(timer); };
  }, [apiBase, job, notify, projectId, token]);

  function chooseCandidate(candidate: ClipCandidate) {
    setSelectedId(candidate.id);
    setEditStart(candidate.start_seconds);
    setEditEnd(candidate.end_seconds);
    setCaptionDraft(candidate.caption_data ?? []);
    setFramingX(candidate.framing_data?.position_x ?? 0.5);
    setFramingY(candidate.framing_data?.position_y ?? 0.5);
  }

  async function analyze() {
    if (!token || !projectId || !sourceId) return;
    setBusy(true);
    setError("");
    try {
      const nextJob = await createClipAnalysis(apiBase, token, {
        project_id: projectId,
        source_media_asset_id: sourceId,
        minimum_duration_seconds: minimum,
        maximum_duration_seconds: maximum,
        ...(targetDurations.length ? { target_durations_seconds: targetDurations } : {}),
      });
      setJob(nextJob);
      notify("Clip analysis queued. The original source remains unchanged.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create analysis.");
    } finally {
      setBusy(false);
    }
  }

  async function uploadSource(file: File | undefined) {
    if (!file || !token || !projectId) return;
    setUploading(true);
    setError("");
    try {
      setUploadProgress(0);
      const uploaded = await uploadMedia(apiBase, token, file, setUploadProgress, projectId);
      setAssets((items) => [uploaded.asset, ...items.filter((item) => item.id !== uploaded.asset.id)]);
      setSourceId(uploaded.asset.id);
      notify("Video uploaded into the selected project.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Video upload failed.");
    } finally {
      setUploading(false);
    }
  }

  async function refreshCandidates() {
    if (!projectId || !token) return;
    setCandidates(await listClipCandidates(apiBase, token, projectId));
  }

  async function saveRankingPreferences() {
    if (!token || !projectId) return;
    try {
      setCandidates(await rankClipCandidates(apiBase, token, projectId, rankingPreferences));
      notify("Candidate ranking updated using your weights.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update ranking preferences.");
    }
  }

  async function saveBoundaries() {
    if (!selectedCandidate || !token) return;
    setBusy(true);
    try {
      const updated = await updateClipCandidate(apiBase, token, selectedCandidate.id, {
        start_seconds: editStart,
        end_seconds: editEnd,
      });
      setCandidates((items) => items.map((item) => item.id === updated.id ? updated : item));
      notify("Clip boundaries saved.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save clip boundaries.");
    } finally {
      setBusy(false);
    }
  }

  async function setStatus(candidate: ClipCandidate, action: "approve" | "reject") {
    if (!token) return;
    try {
      const updated = await setClipCandidateStatus(apiBase, token, candidate.id, action);
      setCandidates((items) => items.map((item) => item.id === updated.id ? updated : item));
      setSelectedForExport((items) => action === "approve"
        ? [...new Set([...items, candidate.id])]
        : items.filter((id) => id !== candidate.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update candidate.");
    }
  }

  async function saveCaptions() {
    if (!selectedCandidate || !token) return;
    try {
      const updated = await updateClipCaptions(apiBase, token, selectedCandidate.id, captionDraft);
      setCandidates((items) => items.map((item) => item.id === updated.id ? updated : item));
      notify("Timed captions saved.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save captions.");
    }
  }

  async function saveFraming() {
    if (!selectedCandidate || !token) return;
    try {
      const updated = await updateClipFraming(apiBase, token, selectedCandidate.id, {
        aspect_ratio: aspectRatio,
        position_x: framingX,
        position_y: framingY,
      });
      setCandidates((items) => items.map((item) => item.id === updated.id ? updated : item));
      notify("Manual crop position saved. Face tracking is not available.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save crop settings.");
    }
  }

  async function queueExport() {
    if (!token || !selectedForExport.length) return;
    setBusy(true);
    setError("");
    try {
      const nextJob = await createClipExport(apiBase, token, {
        candidate_ids: selectedForExport,
        aspect_ratio: aspectRatio,
        resolution,
        captions: captionsEnabled,
        caption_position: captionPosition,
        caption_theme: captionTheme,
        caption_font_size: captionFontSize,
        caption_color: captionColor,
        caption_background_color: captionBackgroundColor,
        caption_outline_color: captionOutlineColor,
        animated_highlighting: false,
        ...(watermark.trim() ? { watermark: watermark.trim() } : {}),
      });
      setJob(nextJob);
      notify("Batch export queued.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not queue batch export.");
    } finally {
      setBusy(false);
    }
  }

  async function exportCaptions(format: "srt" | "vtt") {
    if (!selectedCandidate || !token) return;
    try {
      saveBlob(
        await downloadClipCaptions(apiBase, token, selectedCandidate.id, format),
        `${candidateTitle(selectedCandidate).replace(/[^a-z0-9]+/gi, "-").toLowerCase()}.${format}`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not download captions.");
    }
  }

  if (!token) {
    return <ConnectForm apiBase={apiBase} onConnected={setToken} setApiBase={setApiBase} />;
  }

  return (
    <div className="clipper-workspace">
      <Card className="clipper-source-card">
        <div className="clipper-source-controls">
          <Field label="Project">
          <SelectInput onChange={(event) => { setProjectId(event.target.value); setSourceId(""); setCandidates([]); setSelectedId(""); setJob(null); }} value={projectId}>
              <option value="">Select a project</option>
              {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
            </SelectInput>
          </Field>
          <Field label="Source video">
            <SelectInput onChange={(event) => { setSourceId(event.target.value); setSelectedId(""); setJob(null); }} value={sourceId}>
              <option value="">Select project video</option>
              {projectVideos.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}{asset.duration_seconds ? ` · ${timecode(asset.duration_seconds)}` : ""}</option>)}
            </SelectInput>
          </Field>
          <label className="button button-secondary button-sm clipper-upload">
            {uploading ? <LoaderCircle className="spin" size={14} /> : <Upload size={14} />}
            Upload video
            <input accept="video/*" disabled={!projectId || uploading} onChange={(event) => void uploadSource(event.target.files?.[0])} type="file" />
          </label>
          <Button disabled={!projectId || !sourceId || busy || (job !== null && ["queued", "processing"].includes(job.status))} icon={busy ? <LoaderCircle className="spin" size={14} /> : <Sparkles size={14} />} onClick={() => void analyze()} size="sm" variant="primary">Analyze source</Button>
        </div>
        <div className="clipper-analysis-options">
          <Field label="Minimum clip (seconds)"><TextInput max="180" min="3" onChange={(event) => setMinimum(Number(event.target.value))} type="number" value={minimum} /></Field>
          <Field label="Maximum clip (seconds)"><TextInput max="180" min="5" onChange={(event) => setMaximum(Number(event.target.value))} type="number" value={maximum} /></Field>
          <div className="clipper-duration-targets" aria-label="Target clip durations">
            <span>Target durations</span>
            {([15, 30, 45, 60] as const).map((seconds) => (
              <label className="clipper-checkbox" key={seconds}>
                <input
                  checked={targetDurations.includes(seconds)}
                  onChange={(event) => setTargetDurations((values) => event.target.checked
                    ? [...values, seconds].sort((a, b) => a - b)
                    : values.filter((value) => value !== seconds))}
                  type="checkbox"
                />
                {seconds}s
              </label>
            ))}
          </div>
          <p>Boundaries snap to transcript segments when available. Without a local transcript, scene and silence windows are analyzed without fabricated captions.</p>
        </div>
        <div className="clipper-capabilities" aria-label="Processing capabilities">
          <Badge tone={capabilities?.scene_detection.available ? "cyan" : "neutral"}>Scene detection {capabilities?.scene_detection.available ? "ready" : "unavailable"}</Badge>
          <Badge tone={capabilities?.silence_detection.available ? "cyan" : "amber"}>Silence detection {capabilities?.silence_detection.available ? "ready" : "unavailable"}</Badge>
          <Badge tone={capabilities?.transcription.available ? "green" : "amber"}>Transcription {capabilities?.transcription.provider ?? "requires saved transcript or local provider"}</Badge>
          <Badge tone={capabilities?.rendering.available ? "cyan" : "amber"}>FFmpeg {capabilities?.rendering.available ? "ready" : "unavailable"}</Badge>
          <Badge>Segment timestamps · word timestamps unavailable</Badge>
          <Badge>Face tracking unavailable · manual crop</Badge>
        </div>
        {uploading ? <div className="clipper-upload-progress" role="status"><span>Uploading video</span><progress max={100} value={uploadProgress}>{uploadProgress}%</progress><strong>{uploadProgress}%</strong></div> : null}
        {job?.job_type === "smart_clip_analysis" && job.status === "completed" ? (
          <div className="clipper-analysis-timeline">
            <strong>Detected scenes and pauses</strong>
            <div className="clipper-scene-track" aria-label="Detected scene timeline">
              {analyzedScenes.map((scene, index) => (
                <i
                  key={`${scene.start_seconds}-${index}`}
                  style={{
                    left: `${sourceDuration ? scene.start_seconds / sourceDuration * 100 : 0}%`,
                    width: `${sourceDuration ? Math.max(1, (scene.end_seconds - scene.start_seconds) / sourceDuration * 100) : 0}%`,
                  }}
                  title={`Scene ${index + 1}: ${timecode(scene.start_seconds)}–${timecode(scene.end_seconds)}`}
                />
              ))}
              {analyzedSilences.map((silence, index) => (
                <b
                  key={`silence-${silence.start_seconds}-${index}`}
                  style={{
                    left: `${sourceDuration ? silence.start_seconds / sourceDuration * 100 : 0}%`,
                    width: `${sourceDuration ? Math.max(0.5, (silence.end_seconds - silence.start_seconds) / sourceDuration * 100) : 0}%`,
                  }}
                  title={`Detected silence: ${timecode(silence.start_seconds)}–${timecode(silence.end_seconds)}`}
                />
              ))}
            </div>
            <small>{analyzedScenes.length} scenes · {analyzedSilences.length} silence intervals · {String(job.output_data?.analysis_mode ?? "analysis")}</small>
          </div>
        ) : null}
        {selectedProject ? <div className="clipper-source-meta"><FileVideo2 size={14} /><span>{source?.name ?? "Choose a video from this project"}</span><small>{source?.duration_seconds ? `${source.duration_seconds.toFixed(1)} sec` : "Source is preserved"}</small></div> : null}
        {job && ["queued", "processing"].includes(job.status) ? (
          <div className="clipper-job-progress" role="status">
            <span>{job.job_type === "smart_clip_analysis" ? "Analyzing transcript and scenes" : "Rendering approved clips"}</span>
            <progress max={100} value={job.progress}>{job.progress}%</progress>
            <strong>{job.progress}%</strong>
            <Button onClick={() => void cancelClipJob(apiBase, token, job.id).then(setJob).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Could not cancel job."))} size="sm">Cancel</Button>
          </div>
        ) : null}
        {job?.status === "failed" && job.retry_count < job.max_retries
          ? <Button icon={<RefreshCw size={14} />} onClick={() => void retryClipJob(apiBase, token, job.id).then(setJob).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Could not retry job."))} size="sm">Retry {job.job_type === "smart_clip_analysis" ? "analysis" : "export"}</Button>
          : null}
        {error ? <p className="error-message" role="alert">{error}</p> : null}
      </Card>

      {current === "Batch export" ? (
        <div className="clipper-layout clipper-export-layout">
          <Card className="clipper-candidate-panel">
            <SectionHeading title="Approved clips" description="Select clips to render. Only user-approved candidates can be exported." />
            {approved.length ? approved.map((candidate) => (
              <label className="clipper-export-row" key={candidate.id}>
                <input checked={selectedForExport.includes(candidate.id)} onChange={(event) => setSelectedForExport((ids) => event.target.checked ? [...new Set([...ids, candidate.id])] : ids.filter((id) => id !== candidate.id))} type="checkbox" />
                <span><strong>{candidateTitle(candidate)}</strong><small>{timecode(candidate.start_seconds)}–{timecode(candidate.end_seconds)} · {candidate.end_seconds - candidate.start_seconds}s</small></span>
                {candidate.exported_media_asset_id ? <Badge tone="green">Exported</Badge> : null}
              </label>
            )) : <p className="workspace-copy">Approve clips in Highlights before adding them to a batch.</p>}
            <Button disabled={!selectedForExport.length || busy || (job !== null && ["queued", "processing"].includes(job.status))} icon={<Download size={15} />} onClick={() => void queueExport()} variant="primary">Export {selectedForExport.length} clips</Button>
          </Card>
          <Card className="clipper-inspector">
            <SectionHeading title="Export settings" description="FFmpeg renders H.264 video and AAC audio to local project media." />
            <Field label="Aspect ratio"><SelectInput onChange={(event) => setAspectRatio(event.target.value as ClipExportInput["aspect_ratio"])} value={aspectRatio}><option value="9:16">9:16 · Shorts / Reels / TikTok</option><option value="1:1">1:1 · Square</option><option value="4:5">4:5 · Portrait feed</option><option value="16:9">16:9 · Landscape</option></SelectInput></Field>
            <Field label="Resolution"><SelectInput onChange={(event) => setResolution(event.target.value as ClipExportInput["resolution"])} value={resolution}><option value="1080p">1080p</option><option value="720p">720p</option></SelectInput></Field>
            <label className="clipper-checkbox"><input checked={captionsEnabled} onChange={(event) => setCaptionsEnabled(event.target.checked)} type="checkbox" /> Add styled burned-in captions and selectable subtitles</label>
            <Field label="Caption position"><SelectInput onChange={(event) => setCaptionPosition(event.target.value as ClipExportInput["caption_position"])} value={captionPosition}><option value="bottom">Bottom safe zone</option><option value="center">Center</option><option value="top">Top safe zone</option></SelectInput></Field>
            <Field label="Caption theme"><SelectInput onChange={(event) => setCaptionTheme(event.target.value as ClipExportInput["caption_theme"])} value={captionTheme}><option value="boxed">Boxed</option><option value="outline">Outlined</option><option value="minimal">Minimal</option></SelectInput></Field>
            <Field label="Caption size"><TextInput max="48" min="18" onChange={(event) => setCaptionFontSize(Number(event.target.value))} type="number" value={captionFontSize} /></Field>
            <Field label="Caption color"><TextInput onChange={(event) => setCaptionColor(event.target.value)} type="color" value={captionColor} /></Field>
            <Field label="Caption background"><TextInput onChange={(event) => setCaptionBackgroundColor(event.target.value)} type="color" value={captionBackgroundColor} /></Field>
            <Field label="Caption outline"><TextInput onChange={(event) => setCaptionOutlineColor(event.target.value)} type="color" value={captionOutlineColor} /></Field>
            <label className="clipper-checkbox" title="The configured transcription provider supplies segment, not word, timestamps."><input disabled type="checkbox" /> Animated word highlighting unavailable (no word timestamps)</label>
            <Field label="Optional text watermark"><TextInput maxLength={100} onChange={(event) => setWatermark(event.target.value)} placeholder="Leave blank for none" value={watermark} /></Field>
            {job?.job_type === "smart_clip_export" && job.output_data ? <p className="workspace-copy">{String(job.output_data.completed ?? 0)} of {String(job.output_data.total ?? selectedForExport.length)} completed.</p> : null}
          </Card>
        </div>
      ) : (
        <div className="clipper-layout">
          <Card className="clipper-preview-panel">
            <div className="clipper-preview-heading">
              <SectionHeading title="Source preview" description={selectedCandidate ? `${candidateTitle(selectedCandidate)} · ${timecode(selectedCandidate.start_seconds)}–${timecode(selectedCandidate.end_seconds)}` : "Choose a project video and analyze it to review transcript-backed highlights."} />
              {selectedCandidate ? <Badge tone={selectedCandidate.status === "approved" ? "green" : "violet"}>{selectedCandidate.status}</Badge> : null}
            </div>
            {previewUrl ? <video className="clipper-video" controls key={previewUrl} onLoadedMetadata={(event) => { if (selectedCandidate && !selectedCandidate.exported_media_asset_id) event.currentTarget.currentTime = selectedCandidate.start_seconds; }} ref={videoRef} src={previewUrl} /> : <div className="clipper-empty-video"><Play size={26} /><span>{source ? "Loading source preview…" : "No video selected"}</span></div>}
            {selectedCandidate ? <div className="clipper-timeline"><div className="clipper-timeline-label"><Scissors size={14} /> Clip window <span>{timecode(selectedCandidate.start_seconds)}–{timecode(selectedCandidate.end_seconds)}</span></div><div className="clipper-track"><i style={{ left: `${sourceDuration ? selectedCandidate.start_seconds / sourceDuration * 100 : 0}%`, width: `${sourceDuration ? Math.max(2, (selectedCandidate.end_seconds - selectedCandidate.start_seconds) / sourceDuration * 100) : 0}%` }} /></div></div> : null}
            {selectedCandidate ? <div className="clipper-transcript">
              <strong>Transcript segments</strong>
              {selectedCandidate.caption_data?.length ? selectedCandidate.caption_data.map((caption, index) => (
                <p key={`${caption.start_seconds}-${index}`}>
                  <small>{timecode(caption.start_seconds)}–{timecode(caption.end_seconds)}{caption.speaker_label ? ` · ${caption.speaker_label}` : ""}</small>
                  <span>{caption.text}</span>
                </p>
              )) : <p>{selectedCandidate.transcript_text ?? "No transcript available; this candidate was generated from scene and silence boundaries."}</p>}
            </div> : null}
          </Card>

          <Card className="clipper-candidate-panel">
            <SectionHeading title="Transcript highlights" description="Heuristic ranking explains transcript evidence; it does not predict virality." action={<Button onClick={() => void refreshCandidates()} size="sm">Refresh</Button>} />
            <details className="clipper-ranking-settings">
              <summary>Ranking preferences</summary>
              {Object.entries(defaultRanking).map(([key, defaultValue]) => (
                <Field key={key} label={`${factorLabels[key]} · ${rankingPreferences[key as keyof ClipRankPreferences].toFixed(1)}`}>
                  <input aria-label={`${factorLabels[key]} weight`} max="3" min="0" onChange={(event) => setRankingPreferences((items) => ({ ...items, [key]: Number(event.target.value) }))} step="0.1" type="range" value={rankingPreferences[key as keyof ClipRankPreferences] ?? defaultValue} />
                </Field>
              ))}
              <Button onClick={() => void saveRankingPreferences()} size="sm">Apply ranking</Button>
            </details>
            {candidates.length && projectId ? <div className="clipper-candidate-list">
              {candidates.map((candidate, index) => (
                <button aria-pressed={candidate.id === selectedId} className={`clipper-candidate-row ${candidate.id === selectedId ? "selected" : ""}`} key={candidate.id} onClick={() => chooseCandidate(candidate)} type="button">
                  <span className="clipper-rank">{String(index + 1).padStart(2, "0")}</span>
                  <span className="clipper-candidate-text"><strong>{candidateTitle(candidate)}</strong><small>{timecode(candidate.start_seconds)}–{timecode(candidate.end_seconds)} · {(candidate.end_seconds - candidate.start_seconds).toFixed(0)} sec</small><span>{candidate.explanation}</span></span>
                  <Badge tone={candidate.status === "approved" ? "green" : candidate.status === "rejected" ? "neutral" : "violet"}>{Math.round(candidate.score ?? 0)}</Badge>
                </button>
              ))}
            </div> : <div className="clipper-no-candidates"><Sparkles size={20} /><strong>No analysis candidates yet</strong><span>Choose a project video, then start analysis. Results appear only after processing real video and transcript data.</span></div>}
            {selectedCandidate ? <div className="clipper-explanation">
              <strong>Ranking evidence</strong>
              {Object.entries(selectedCandidate.scoring_factors ?? {}).map(([factor, value]) => <div key={factor}><span>{factorLabels[factor] ?? factor}</span><meter max={1} min={0} value={value} /><b>{Math.round(Number(value) * 100)}%</b></div>)}
            </div> : null}
          </Card>

          {selectedCandidate ? (
            <Card className="clipper-inspector">
              {current === "Captions" ? (
                <>
                  <SectionHeading title="Timed caption editor" description="Timing is relative to the source timeline and must remain inside this clip." />
                  <div className="clipper-caption-list">{captionDraft.map((caption, index) => <div className="clipper-caption-row" key={`${caption.start_seconds}-${index}`}>
                    <span>{timecode(caption.start_seconds)}–{timecode(caption.end_seconds)}</span>
                    <textarea aria-label={`Caption ${index + 1}`} onChange={(event) => setCaptionDraft((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, text: event.target.value } : item))} value={caption.text} />
                    <TextInput aria-label={`Highlighted words for caption ${index + 1}`} onChange={(event) => setCaptionDraft((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, highlighted_words: event.target.value.split(",").map((word) => word.trim()).filter(Boolean) } : item))} placeholder="Highlight words, comma-separated" value={caption.highlighted_words.join(", ")} />
                  </div>)}</div>
                  <div className="clipper-actions"><Button onClick={() => void saveCaptions()} size="sm" variant="primary">Save captions</Button><Button onClick={() => void exportCaptions("srt")} size="sm">Download SRT</Button><Button onClick={() => void exportCaptions("vtt")} size="sm">Download VTT</Button></div>
                </>
              ) : (
                <>
                  <SectionHeading title="Clip inspector" description="Manually adjust boundaries and crop. Face-aware tracking is not integrated." />
                  <Field label="Start (seconds)"><TextInput max={source?.duration_seconds ?? undefined} min="0" onChange={(event) => setEditStart(Number(event.target.value))} step="0.1" type="number" value={editStart} /></Field>
                  <Field label="End (seconds)"><TextInput max={source?.duration_seconds ?? undefined} min={editStart + 0.1} onChange={(event) => setEditEnd(Number(event.target.value))} step="0.1" type="number" value={editEnd} /></Field>
                  <Button disabled={busy} onClick={() => void saveBoundaries()} size="sm">Save clip boundaries</Button>
                  <Field label="Output framing"><SelectInput onChange={(event) => setAspectRatio(event.target.value as ClipExportInput["aspect_ratio"])} value={aspectRatio}><option value="9:16">9:16 Vertical</option><option value="1:1">1:1 Square</option><option value="4:5">4:5 Portrait</option><option value="16:9">16:9 Landscape</option></SelectInput></Field>
                  <Field label="Manual horizontal crop"><input aria-label="Manual horizontal crop" max="1" min="0" onChange={(event) => setFramingX(Number(event.target.value))} step="0.01" type="range" value={framingX} /></Field>
                  <Field label="Manual vertical crop"><input aria-label="Manual vertical crop" max="1" min="0" onChange={(event) => setFramingY(Number(event.target.value))} step="0.01" type="range" value={framingY} /></Field>
                  <Button onClick={() => void saveFraming()} size="sm">Save manual crop</Button>
                  <div className="clipper-actions"><Button disabled={selectedCandidate.status === "approved"} icon={<Check size={14} />} onClick={() => void setStatus(selectedCandidate, "approve")} size="sm" variant="primary">Approve</Button><Button disabled={selectedCandidate.status === "rejected"} icon={<X size={14} />} onClick={() => void setStatus(selectedCandidate, "reject")} size="sm">Reject</Button></div>
                  {selectedCandidate.exported_media_asset_id ? <Badge tone="green">Exported to project media</Badge> : null}
                </>
              )}
            </Card>
          ) : null}
          {selectedCandidate && current === "Overview" ? <Card className="clipper-inspector clipper-broll-card"><SectionHeading title="Project B-roll" description="Suggestions are only from your own project's uploaded video assets." /><Button onClick={async () => { try { const response = await fetch(`${apiBase.replace(/\/+$/, "")}/api/v1/clipper/projects/${projectId}/b-roll?candidate_id=${selectedCandidate.id}`, { headers: { Authorization: `Bearer ${token}` } }); if (!response.ok) throw new Error("Could not load B-roll suggestions."); setBRoll(await response.json() as typeof bRoll); } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not load B-roll suggestions."); } }} size="sm">Find related footage</Button>{bRoll.map((item) => <div className="clipper-broll-item" key={item.id}><FileVideo2 size={15} /><span><strong>{item.name}</strong><small>{item.reason} {item.matched_terms.join(", ")}</small></span></div>)}{!bRoll.length ? <small>No recommendations loaded.</small> : null}</Card> : null}
        </div>
      )}
      {!selectedProject ? <Card className="workspace-main-card"><p className="workspace-copy">Create a project before selecting source media.</p></Card> : null}
    </div>
  );
}
