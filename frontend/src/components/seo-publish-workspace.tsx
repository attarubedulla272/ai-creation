"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  CalendarDays,
  Check,
  Clapperboard,
  Clock3,
  Image as ImageIcon,
  LoaderCircle,
  ExternalLink,
  RefreshCw,
  ShieldCheck,
  Upload,
  Unplug,
} from "lucide-react";
import Image from "next/image";
import { Badge, Button, Card, Field, SectionHeading, SelectInput, TextInput } from "@/components/ui";
import { useStudioUI } from "@/components/studio-shell";
import {
  authenticate,
  loadMediaPreview,
  uploadMedia,
  type MediaAsset,
} from "@/lib/media-api";
import { listStudioProjects, type StudioProject } from "@/lib/timeline-api";
import { listClipCandidates, type ClipCandidate } from "@/lib/clipper-api";
import {
  createPublication,
  beginYouTubeAnalyticsAuthorization,
  beginYouTubeConnection,
  cancelYouTubeUpload,
  createYouTubeUpload,
  disconnectYouTubeChannel,
  getYouTubeAnalytics,
  getPublishingCapabilities,
  getPublicationRevisions,
  listPublishingMedia,
  listPublicationCalendar,
  listYouTubeConnections,
  listYouTubeUploads,
  listPublications,
  renderThumbnail,
  suggestPublicationTitles,
  updatePublication,
  retryYouTubeUpload,
  type YouTubeAnalytics,
  type YouTubeConnection,
  type YouTubeUploadJob,
  uploadYouTubeThumbnail,
  type Publication,
  type PublicationInput,
  type PublicationPlatform,
  type PublicationRevision,
} from "@/lib/publishing-api";

const TOKEN_KEY = "ai-creator-studio:media-token";

function splitList(value: string) {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function parseChapters(value: string) {
  return value.split("\n").map((line) => {
    const match = line.trim().match(/^(\d{1,2}:)?\d{1,2}:\d{2}\s+(.+)$/);
    if (!match) return null;
    const timecode = line.trim().split(/\s+/, 1)[0].split(":").map(Number);
    const timestampSeconds = timecode.length === 3
      ? timecode[0] * 3600 + timecode[1] * 60 + timecode[2]
      : timecode[0] * 60 + timecode[1];
    return { timestamp_seconds: timestampSeconds, title: match[2].trim() };
  }).filter((chapter): chapter is { timestamp_seconds: number; title: string } => chapter !== null);
}

function chapterText(publication?: Publication) {
  return (publication?.metadata_json?.chapters ?? [])
    .map((chapter) => {
      const hours = Math.floor(chapter.timestamp_seconds / 3600);
      const minutes = Math.floor((chapter.timestamp_seconds % 3600) / 60);
      const seconds = chapter.timestamp_seconds % 60;
      const time = hours
        ? `${hours}:${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`
        : `${minutes}:${seconds.toString().padStart(2, "0")}`;
      return `${time} ${chapter.title}`;
    })
    .join("\n");
}

function ConnectWorkspace({ onConnected }: { onConnected: (token: string) => void }) {
  const [apiBase, setApiBase] = useState("http://localhost:8000");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [newAccount, setNewAccount] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const token = await authenticate(apiBase, email, password, newAccount);
      window.sessionStorage.setItem(TOKEN_KEY, token);
      window.sessionStorage.setItem("ai-creator-studio:backend-url", apiBase);
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
      <SectionHeading
        title="Connect your publishing workspace"
        description="Sign in to save release drafts, thumbnails, and calendar entries to your account."
      />
      <form className="clipper-connect-form" onSubmit={(event) => void submit(event)}>
        <Field label="API address"><TextInput value={apiBase} onChange={(event) => setApiBase(event.target.value)} /></Field>
        <Field label="Email"><TextInput autoComplete="email" required type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></Field>
        <Field label="Password"><TextInput autoComplete={newAccount ? "new-password" : "current-password"} required type="password" value={password} onChange={(event) => setPassword(event.target.value)} /></Field>
        <label className="clipper-checkbox"><input checked={newAccount} onChange={(event) => setNewAccount(event.target.checked)} type="checkbox" /> Create a new account</label>
        {error ? <p className="error-message" role="alert">{error}</p> : null}
        <Button disabled={busy} icon={busy ? <LoaderCircle className="spin" size={15} /> : <ShieldCheck size={15} />} type="submit" variant="primary">Connect</Button>
      </form>
    </Card>
  );
}

function YouTubeWorkspace({
  apiBase,
  token,
  current,
  onEnsurePublication,
  notify,
}: {
  apiBase: string;
  token: string;
  current: string;
  onEnsurePublication: () => Promise<Publication | undefined>;
  notify: (message: string) => void;
}) {
  const [connections, setConnections] = useState<YouTubeConnection[]>([]);
  const [selectedConnectionId, setSelectedConnectionId] = useState("");
  const [uploads, setUploads] = useState<YouTubeUploadJob[]>([]);
  const [privacy, setPrivacy] = useState<"private" | "unlisted" | "public">("private");
  const [publishAt, setPublishAt] = useState("");
  const [analytics, setAnalytics] = useState<YouTubeAnalytics | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [hasLoaded, setHasLoaded] = useState(false);
  const hasActiveUpload = uploads.some((job) => job.status === "queued" || job.status === "processing");
  const selectedConnection = connections.find((item) => item.id === selectedConnectionId);

  const refreshConnections = useCallback(async () => {
    const result = await listYouTubeConnections(apiBase, token);
    setConnections(result);
    setSelectedConnectionId((currentId) => (
      result.some((item) => item.id === currentId)
        ? currentId
        : result[0]?.id ?? ""
    ));
  }, [apiBase, token]);

  const refreshUploads = useCallback(async () => {
    setUploads(await listYouTubeUploads(apiBase, token));
  }, [apiBase, token]);

  useEffect(() => {
    let active = true;
    void Promise.all([
      listYouTubeConnections(apiBase, token),
      listYouTubeUploads(apiBase, token),
    ]).then(([nextConnections, nextUploads]) => {
      if (!active) return;
      setConnections(nextConnections);
      setSelectedConnectionId((currentId) => (
        nextConnections.some((item) => item.id === currentId)
          ? currentId
          : nextConnections[0]?.id ?? ""
      ));
      setUploads(nextUploads);
      setHasLoaded(true);
    }).catch((reason: unknown) => {
      if (active) {
        setHasLoaded(true);
        setError(reason instanceof Error ? reason.message : "Could not load YouTube publishing data.");
      }
    });

    const url = new URL(window.location.href);
    const oauthResult = url.searchParams.get("youtube_connection");
    if (oauthResult) {
      url.searchParams.delete("youtube_connection");
      window.history.replaceState({}, "", url);
      if (oauthResult === "connected") {
        notify("YouTube channel connected. Access tokens remain on the backend.");
        void Promise.resolve().then(refreshConnections).catch((reason: unknown) => {
          if (active) setError(reason instanceof Error ? reason.message : "Could not refresh channels.");
        });
      } else {
        const messages: Record<string, string> = {
          cancelled: "YouTube authorization was cancelled.",
          invalid_state: "YouTube authorization failed its state check. Start again.",
          expired_state: "The YouTube authorization expired. Start again.",
          channel_mismatch: "The analytics authorization returned a different YouTube channel.",
          missing_scope: "Google did not grant the requested YouTube permissions.",
          missing_refresh_token: "Google did not return an offline refresh token. Reconnect and consent.",
          oauth_failed: "Google authorization failed. Check OAuth configuration and try again.",
        };
        void Promise.resolve().then(() => {
          if (active) setError(messages[oauthResult] ?? "YouTube authorization did not complete.");
        });
      }
    }

    return () => { active = false; };
  }, [apiBase, notify, refreshConnections, token]);

  useEffect(() => {
    if (!hasActiveUpload) return;
    const timer = window.setInterval(() => {
      void refreshUploads().catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "Could not refresh upload progress.");
      });
    }, 1200);
    return () => window.clearInterval(timer);
  }, [hasActiveUpload, refreshUploads]);

  async function startOAuth(
    start: () => Promise<{ authorization_url: string }>,
  ) {
    setBusy(true);
    setError("");
    try {
      const result = await start();
      window.location.assign(result.authorization_url);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start Google authorization.");
      setBusy(false);
    }
  }

  async function connect() {
    await startOAuth(() => beginYouTubeConnection(apiBase, token));
  }

  async function disconnect() {
    if (!selectedConnection) return;
    setBusy(true);
    setError("");
    try {
      const result = await disconnectYouTubeChannel(apiBase, token, selectedConnection.id);
      setConnections((items) => items.filter((item) => item.id !== selectedConnection.id));
      setSelectedConnectionId("");
      setAnalytics(null);
      if (result.warning) setError(result.warning);
      else notify("YouTube channel disconnected and its Google token revoked.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not disconnect the channel.");
    } finally {
      setBusy(false);
    }
  }

  async function upload() {
    if (!selectedConnection) {
      setError("Connect and select a YouTube channel before uploading.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const publication = await onEnsurePublication();
      if (!publication) {
        setError("Save a titled YouTube release from Metadata before uploading.");
        return;
      }
      const job = await createYouTubeUpload(apiBase, token, publication.id, {
        connection_id: selectedConnection.id,
        privacy_status: privacy,
        publish_at: publishAt ? new Date(publishAt).toISOString() : null,
      });
      setUploads((items) => [job, ...items.filter((item) => item.id !== job.id)]);
      notify("YouTube upload queued. The platform confirms success only after upload completes.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not queue YouTube upload.");
    } finally {
      setBusy(false);
    }
  }

  async function controlUpload(jobId: string, action: "cancel" | "retry") {
    setError("");
    try {
      const job = action === "cancel"
        ? await cancelYouTubeUpload(apiBase, token, jobId)
        : await retryYouTubeUpload(apiBase, token, jobId);
      setUploads((items) => items.map((item) => item.id === job.id ? job : item));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : `Could not ${action} this upload.`);
    }
  }

  async function retryThumbnail(job: YouTubeUploadJob) {
    const publicationId = job.input_data?.publication_id;
    if (!publicationId) return;
    setError("");
    try {
      await uploadYouTubeThumbnail(apiBase, token, publicationId);
      setUploads((items) => items.map((item) => item.id === job.id
        ? {
            ...item,
            output_data: {
              ...(item.output_data ?? {}),
              thumbnail_uploaded: true,
              thumbnail_warning: undefined,
            },
          }
        : item));
      notify("YouTube thumbnail confirmed by the official API.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not retry the YouTube thumbnail.");
    }
  }

  async function authorizeAnalytics() {
    if (!selectedConnection) return;
    await startOAuth(() => beginYouTubeAnalyticsAuthorization(
      apiBase,
      token,
      selectedConnection.id,
    ));
  }

  async function loadAnalytics() {
    if (!selectedConnection) return;
    setBusy(true);
    setError("");
    try {
      setAnalytics(await getYouTubeAnalytics(apiBase, token, selectedConnection.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not retrieve YouTube Analytics.");
    } finally {
      setBusy(false);
    }
  }

  const dailyRows = analytics?.daily.rows ?? [];
  const headers = analytics?.daily.columnHeaders ?? [];
  const metricTotals = ["views", "estimatedMinutesWatched", "averageViewDuration", "likes", "comments", "subscribersGained"].map((name) => {
    const index = headers.findIndex((header) => header.name === name);
    if (index < 0 || !dailyRows.length) return [name, null] as const;
    const values = dailyRows.map((row) => row[index]).filter((value): value is number => typeof value === "number");
    const total = name === "averageViewDuration"
      ? values.length ? Math.round(values.reduce((sum, value) => sum + value, 0) / values.length) : null
      : values.reduce((sum, value) => sum + value, 0);
    return [name, total] as const;
  });
  const metricLabels: Record<string, string> = {
    views: "Views",
    estimatedMinutesWatched: "Minutes watched",
    averageViewDuration: "Average view duration (seconds)",
    likes: "Likes",
    comments: "Comments",
    subscribersGained: "Subscribers gained",
  };

  return (
    <div className="youtube-workspace">
      <Card className="workspace-main-card">
        <SectionHeading
          title={current === "Analytics" ? "YouTube Analytics" : "Official YouTube publishing"}
          description={current === "Analytics"
            ? "Provider-backed channel metrics only. YouTube reporting can be delayed or omit unavailable metrics."
            : "Connect an authorized channel, then explicitly upload a saved release package."}
          action={<Badge tone={selectedConnection?.status === "connected" ? "green" : "amber"}>{selectedConnection?.status === "connected" ? "Channel connected" : "Not connected"}</Badge>}
        />
        <div className="youtube-channel-row">
          <div className="youtube-channel-info">
            <Clapperboard size={20} />
            <span>
              <strong>{selectedConnection?.channel_title ?? "No YouTube channel connected"}</strong>
              <small>{selectedConnection?.channel_custom_url ?? "Tokens are encrypted and never sent to this page."}</small>
            </span>
          </div>
          <div className="youtube-channel-actions">
            {connections.length ? (
              <Field label="Channel">
                <SelectInput value={selectedConnectionId} onChange={(event) => { setSelectedConnectionId(event.target.value); setAnalytics(null); }}>
                  {connections.map((connection) => <option key={connection.id} value={connection.id}>{connection.channel_title}</option>)}
                </SelectInput>
              </Field>
            ) : null}
            <Button disabled={busy} icon={busy ? <LoaderCircle className="spin" size={15} /> : <Clapperboard size={15} />} onClick={() => void connect()} variant="primary">Connect YouTube</Button>
            {selectedConnection ? <Button disabled={busy} icon={<Unplug size={15} />} onClick={() => void disconnect()}>Disconnect</Button> : null}
          </div>
        </div>
        {selectedConnection?.status === "reauthorization_required" ? <p className="error-message">Google authorization expired or was revoked. Reconnect the channel to continue.</p> : null}

        {current === "Analytics" ? (
          <div className="youtube-analytics-panel">
            {selectedConnection && !selectedConnection.analytics_enabled ? (
              <div className="notice-strip"><ShieldCheck size={15} /><span>Analytics uses a separate Google OAuth consent. No analytics are available until granted.</span></div>
            ) : null}
            {selectedConnection && !selectedConnection.analytics_enabled ? (
              <Button disabled={busy} onClick={() => void authorizeAnalytics()}>Authorize analytics access</Button>
            ) : null}
            {selectedConnection?.analytics_enabled ? (
              <Button disabled={busy} icon={busy ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />} onClick={() => void loadAnalytics()}>Refresh official analytics</Button>
            ) : null}
            {analytics ? (
              <>
                <p className="field-hint">Available through {analytics.available_through ?? "no reported date"} · source: YouTube Analytics API</p>
                <div className="analytics-grid">
                  {metricTotals.map(([name, value]) => <div key={name}><span>{metricLabels[name]}</span><strong>{value === null ? "Unavailable" : value.toLocaleString()}</strong><small>{value === null ? "No provider data returned" : "Official channel report"}</small></div>)}
                </div>
                <h3>Daily channel report</h3>
                <div className="youtube-report-table">
                  <div className="youtube-report-row youtube-report-header">{headers.map((header) => <strong key={header.name}>{header.name}</strong>)}</div>
                  {dailyRows.map((row, index) => <div className="youtube-report-row" key={`${String(row[0])}-${index}`}>{row.map((value, cell) => <span key={`${index}-${cell}`}>{String(value)}</span>)}</div>)}
                  {!dailyRows.length ? <p>No report rows are available for this date range.</p> : null}
                </div>
                <h3>Traffic sources</h3>
                <div className="youtube-report-table">
                  {(analytics.traffic_sources.columnHeaders ?? []).map((header) => <strong key={header.name}>{header.name} · </strong>)}
                  {(analytics.traffic_sources.rows ?? []).map((row, index) => <p key={`traffic-${index}`}>{row.map(String).join(" · ")}</p>)}
                  {!analytics.traffic_sources.rows?.length ? <p>No traffic-source rows are available.</p> : null}
                </div>
              </>
            ) : null}
            {!selectedConnection ? <p className="field-hint">Connect a channel to request official analytics.</p> : null}
          </div>
        ) : (
          <>
            <div className="youtube-upload-controls">
              <Field label="Privacy">
                <SelectInput value={privacy} onChange={(event) => setPrivacy(event.target.value as typeof privacy)}>
                  <option value="private">Private</option><option value="unlisted">Unlisted</option><option value="public">Public</option>
                </SelectInput>
              </Field>
              <Field label="YouTube scheduled publish time" hint="Optional native YouTube scheduling. This is separate from the local content calendar.">
                <TextInput disabled={privacy !== "private"} min={new Date().toISOString().slice(0, 16)} onChange={(event) => setPublishAt(event.target.value)} type="datetime-local" value={publishAt} />
              </Field>
              <Button disabled={busy || !selectedConnection || selectedConnection.status !== "connected"} icon={busy ? <LoaderCircle className="spin" size={15} /> : <Upload size={15} />} onClick={() => void upload()} variant="primary">Save release and upload</Button>
            </div>
            <p className="field-hint">The upload uses the currently selected release. A local scheduled date is never treated as a YouTube schedule unless you explicitly set the YouTube publish time above.</p>
            <h3>Upload history</h3>
            {!hasLoaded ? <p className="field-hint">Loading channel and upload history…</p> : null}
            <div className="youtube-upload-list">
              {uploads.map((job) => {
                const output = job.output_data ?? {};
                const videoUrl = typeof output.youtube_url === "string" ? output.youtube_url : null;
                const publicationTitle = typeof output.publication_title === "string" ? output.publication_title : "YouTube video upload";
                return (
                  <article className="youtube-upload-item" key={job.id}>
                    <div className="youtube-upload-heading"><strong>{publicationTitle}</strong><Badge tone={job.status === "completed" ? "green" : job.status === "failed" ? "pink" : job.status === "processing" ? "cyan" : "neutral"}>{job.status}</Badge></div>
                    <small>{new Date(job.created_at).toLocaleString()} · {job.input_data?.privacy_status ?? "privacy unavailable"}</small>
                    {job.status === "queued" || job.status === "processing" ? <progress aria-label={`Upload progress ${job.progress}%`} max={100} value={job.progress}>{job.progress}%</progress> : null}
                    {job.error_message ? <p className="error-message" role="alert">{job.error_message}</p> : null}
                    {typeof output.thumbnail_warning === "string" ? <p className="error-message" role="alert">{output.thumbnail_warning}</p> : null}
                    {videoUrl ? <a href={videoUrl} rel="noreferrer" target="_blank">Open confirmed YouTube video <ExternalLink size={13} /></a> : null}
                    <div className="youtube-upload-actions">
                      {output.thumbnail_uploaded === false ? <Button onClick={() => void retryThumbnail(job)} size="sm">Retry thumbnail</Button> : null}
                      {(job.status === "queued" || job.status === "processing") ? <Button onClick={() => void controlUpload(job.id, "cancel")} size="sm">Cancel</Button> : null}
                      {(job.status === "failed" || job.status === "cancelled") && job.retry_count < job.max_retries ? <Button onClick={() => void controlUpload(job.id, "retry")} size="sm">Retry</Button> : null}
                    </div>
                  </article>
                );
              })}
              {hasLoaded && !uploads.length ? <p className="field-hint">No YouTube uploads yet.</p> : null}
            </div>
          </>
        )}
        {error ? <p className="error-message" role="alert">{error}</p> : null}
      </Card>
    </div>
  );
}

export function SeoPublishWorkspace({ current }: { current: string }) {
  const { notify } = useStudioUI();
  const [apiBase, setApiBase] = useState("http://localhost:8000");
  const [token, setToken] = useState("");
  const [projects, setProjects] = useState<StudioProject[]>([]);
  const [projectsLoaded, setProjectsLoaded] = useState(false);
  const [projectId, setProjectId] = useState("");
  const [media, setMedia] = useState<MediaAsset[]>([]);
  const [candidates, setCandidates] = useState<ClipCandidate[]>([]);
  const [publications, setPublications] = useState<Publication[]>([]);
  const [revisionHistory, setRevisionHistory] = useState<PublicationRevision[]>([]);
  const [calendar, setCalendar] = useState<Publication[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [capabilities, setCapabilities] = useState<Awaited<ReturnType<typeof getPublishingCapabilities>> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [platform, setPlatform] = useState<PublicationPlatform>("youtube");
  const [tags, setTags] = useState("");
  const [hashtags, setHashtags] = useState("");
  const [primaryKeywords, setPrimaryKeywords] = useState("");
  const [secondaryKeywords, setSecondaryKeywords] = useState("");
  const [chapters, setChapters] = useState("");
  const [language, setLanguage] = useState("");
  const [category, setCategory] = useState("");
  const [mediaAssetId, setMediaAssetId] = useState("");
  const [clipCandidateId, setClipCandidateId] = useState("");
  const [thumbnailAssetId, setThumbnailAssetId] = useState("");
  const [entryStatus, setEntryStatus] = useState<"draft" | "ready" | "scheduled">("draft");
  const [scheduledLocal, setScheduledLocal] = useState("");
  const [thumbnailText, setThumbnailText] = useState("");
  const [imageSourceId, setImageSourceId] = useState("");
  const [thumbnailAspect, setThumbnailAspect] = useState<"16:9" | "1:1" | "9:16">("16:9");
  const [thumbnailPosition, setThumbnailPosition] = useState<"top" | "center" | "bottom">("bottom");
  const [fontSize, setFontSize] = useState(64);
  const [textColor, setTextColor] = useState("#FFFFFF");
  const [cropX, setCropX] = useState(0.5);
  const [cropY, setCropY] = useState(0.5);
  const [thumbnailPreview, setThumbnailPreview] = useState<{ assetId: string; url: string } | null>(null);
  const [titleSuggestions, setTitleSuggestions] = useState<string[]>([]);
  const revisionRequestId = useRef(0);

  const selectedPublication = publications.find((item) => item.id === selectedId);
  const projectAssets = useMemo(
    () => media.filter((asset) => asset.project_id === projectId || asset.project_id === null),
    [media, projectId],
  );
  const videos = projectAssets.filter((asset) => asset.media_type === "video");
  const images = projectAssets.filter((asset) => asset.media_type === "image");

  const refresh = useCallback(async (activeToken: string, activeProjectId: string) => {
    const [nextMedia, nextPublications, nextCalendar, nextCandidates] = await Promise.all([
      listPublishingMedia(apiBase, activeToken),
      listPublications(apiBase, activeToken, activeProjectId),
      listPublicationCalendar(apiBase, activeToken),
      listClipCandidates(apiBase, activeToken, activeProjectId),
    ]);
    setMedia(nextMedia);
    setPublications(nextPublications);
    setCalendar(nextCalendar);
    setCandidates(nextCandidates);
  }, [apiBase]);

  useEffect(() => {
    const storedToken = window.sessionStorage.getItem(TOKEN_KEY);
    const storedBase = window.sessionStorage.getItem("ai-creator-studio:backend-url");
    const timer = window.setTimeout(() => {
      if (storedToken) setToken(storedToken);
      if (storedBase) setApiBase(storedBase);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!token) return;
    let active = true;
    void Promise.all([
      listStudioProjects(apiBase, token),
      getPublishingCapabilities(apiBase, token),
    ]).then(([nextProjects, nextCapabilities]) => {
      if (!active) return;
      setProjects(nextProjects);
      setProjectsLoaded(true);
      setCapabilities(nextCapabilities);
      setProjectId((currentProject) => currentProject || nextProjects[0]?.id || "");
    }).catch((reason: unknown) => {
      if (active) {
        setProjectsLoaded(true);
        setError(reason instanceof Error ? reason.message : "Could not load publishing data.");
      }
    });
    return () => { active = false; };
  }, [apiBase, token]);

  useEffect(() => {
    if (!token || !projectId) return;
    let active = true;
    void Promise.resolve().then(() => refresh(token, projectId)).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Could not load project releases.");
    });
    return () => { active = false; };
  }, [projectId, refresh, token]);

  useEffect(() => {
    if (!token || !thumbnailAssetId) return;
    let objectUrl = "";
    let active = true;
    void loadMediaPreview(apiBase, token, thumbnailAssetId).then((url) => {
      if (!active) {
        URL.revokeObjectURL(url);
        return;
      }
      objectUrl = url;
      setThumbnailPreview({ assetId: thumbnailAssetId, url });
    }).catch(() => {
      if (active) setThumbnailPreview(null);
    });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [apiBase, thumbnailAssetId, token]);

  function applyPublication(publication?: Publication) {
    setSelectedId(publication?.id ?? "");
    const metadata = publication?.metadata_json;
    setTitle(publication?.title ?? "");
    setDescription(publication?.description ?? "");
    setPlatform(publication?.platform ?? "youtube");
    setTags((metadata?.tags ?? []).join(", "));
    setHashtags((metadata?.hashtags ?? []).join(", "));
    setPrimaryKeywords((metadata?.primary_keywords ?? []).join(", "));
    setSecondaryKeywords((metadata?.secondary_keywords ?? []).join(", "));
    setChapters(chapterText(publication));
    setLanguage(metadata?.language ?? "");
    setCategory(metadata?.category ?? "");
    setMediaAssetId(publication?.media_asset_id ?? "");
    setClipCandidateId(publication?.clip_candidate_id ?? "");
    setThumbnailAssetId(publication?.thumbnail_asset_id ?? "");
    setThumbnailText(publication?.title ?? "");
    setRevisionHistory([]);
    if (publication && token) {
      const requestId = ++revisionRequestId.current;
      void getPublicationRevisions(apiBase, token, publication.id)
        .then((revisions) => {
          if (revisionRequestId.current === requestId) setRevisionHistory(revisions);
        })
        .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Could not load revision history."));
    } else {
      revisionRequestId.current += 1;
    }
    setEntryStatus(publication?.status === "scheduled" ? "scheduled" : publication?.status === "ready" ? "ready" : "draft");
    setScheduledLocal(publication?.scheduled_at ? new Date(publication.scheduled_at).toISOString().slice(0, 16) : "");
  }

  function makeInput(): PublicationInput {
    return {
      platform,
      title: title.trim(),
      description,
      tags: splitList(tags),
      hashtags: splitList(hashtags),
      primary_keywords: splitList(primaryKeywords),
      secondary_keywords: splitList(secondaryKeywords),
      chapters: parseChapters(chapters),
      language: language.trim() || null,
      category: category.trim() || null,
      media_asset_id: mediaAssetId || null,
      clip_candidate_id: clipCandidateId || null,
      thumbnail_asset_id: thumbnailAssetId || null,
      status: entryStatus,
      scheduled_at: entryStatus === "scheduled" && scheduledLocal
        ? new Date(scheduledLocal).toISOString()
        : null,
    };
  }

  async function savePublication(): Promise<Publication | undefined> {
    if (!token || !projectId || !title.trim()) {
      setError("Choose a project and enter a title before saving.");
      return undefined;
    }
    setBusy(true);
    setError("");
    try {
      const input = makeInput();
      const saved = selectedId
        ? await updatePublication(apiBase, token, selectedId, input)
        : await createPublication(apiBase, token, projectId, input);
      await refresh(token, projectId);
      setSelectedId(saved.id);
      setRevisionHistory(await getPublicationRevisions(apiBase, token, saved.id));
      notify("Release metadata saved with version history.");
      return saved;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save this release.");
    } finally {
      setBusy(false);
    }
  }

  async function uploadImage(file?: File) {
    if (!file || !token || !projectId) return;
    setBusy(true);
    setError("");
    try {
      const uploaded = await uploadMedia(apiBase, token, file, () => {}, projectId);
      await refresh(token, projectId);
      setImageSourceId(uploaded.asset.id);
      notify("Image uploaded to this project's media library.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not upload the image.");
    } finally {
      setBusy(false);
    }
  }

  async function createThumbnail() {
    const text = thumbnailText.trim() || title.trim();
    if (!token || !projectId || !imageSourceId || !text) {
      setError("Select an image and enter thumbnail text first.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await renderThumbnail(apiBase, token, projectId, {
        source_asset_id: imageSourceId,
        title: text,
        aspect_ratio: thumbnailAspect,
        text_position: thumbnailPosition,
        font_size: fontSize,
        text_color: textColor,
        crop_x: cropX,
        crop_y: cropY,
      });
      setThumbnailAssetId(result.asset_id);
      setThumbnailText(text);
      if (selectedId) {
        await updatePublication(apiBase, token, selectedId, {
          ...makeInput(),
          thumbnail_asset_id: result.asset_id,
        });
        setRevisionHistory(await getPublicationRevisions(apiBase, token, selectedId));
      }
      await refresh(token, projectId);
      notify(`Thumbnail rendered locally at ${result.width} × ${result.height}.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not render this thumbnail.");
    } finally {
      setBusy(false);
    }
  }

  async function createTitleSuggestions() {
    if (!token || !title.trim()) {
      setError("Enter a topic or working title first.");
      return;
    }
    setError("");
    try {
      const result = await suggestPublicationTitles(
        apiBase,
        token,
        title,
        splitList(primaryKeywords),
      );
      setTitleSuggestions(result.suggestions);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create title ideas.");
    }
  }

  if (!token) return <ConnectWorkspace onConnected={setToken} />;
  if (!projectsLoaded) {
    return <Card className="workspace-main-card"><SectionHeading title="Loading publishing workspace" description="Retrieving your owned projects and release data." /></Card>;
  }
  if (current === "YouTube" || current === "Analytics") {
    return (
      <YouTubeWorkspace
        apiBase={apiBase}
        current={current}
        notify={notify}
        onEnsurePublication={savePublication}
        token={token}
      />
    );
  }
  if (!projects.length && !error) {
    return <Card className="workspace-main-card"><SectionHeading title="Create a project first" description="Release packages are attached to a project you own." /></Card>;
  }

  return (
    <div className="workspace-columns">
      <Card className="workspace-main-card">
        <SectionHeading
          title={current === "Thumbnail" ? "Thumbnail studio" : current === "Schedule" ? "Content calendar" : current === "Analytics" ? "Publishing and analytics" : "SEO release package"}
          description="Save release metadata locally. Only an explicit YouTube upload sends video content to a platform."
          action={<Badge tone="cyan">{selectedPublication ? `Version ${selectedPublication.version}` : "Local draft"}</Badge>}
        />
        <div className="clipper-controls">
          <Field label="Project">
            <SelectInput value={projectId} onChange={(event) => { setProjectId(event.target.value); applyPublication(); }}>
              {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
            </SelectInput>
          </Field>
          {current !== "Thumbnail" && current !== "Analytics" ? (
            <Field label="Release draft">
                <SelectInput value={selectedId} onChange={(event) => applyPublication(publications.find((item) => item.id === event.target.value))}>
                <option value="">New release package</option>
                {publications.map((publication) => <option key={publication.id} value={publication.id}>{publication.title || "Untitled"} · {publication.status}</option>)}
              </SelectInput>
            </Field>
          ) : null}
        </div>

        {current === "Thumbnail" ? (
          <>
            <div className="clipper-controls">
              <Field label="Source image">
                <SelectInput value={imageSourceId} onChange={(event) => setImageSourceId(event.target.value)}>
                  <option value="">Choose an image from this project</option>
                  {images.map((image) => <option key={image.id} value={image.id}>{image.name}</option>)}
                </SelectInput>
              </Field>
              <label className="clipper-upload-button"><Upload size={15} /> Upload image<input accept="image/jpeg,image/png,image/webp" onChange={(event) => void uploadImage(event.target.files?.[0])} type="file" /></label>
            </div>
            <div className="clipper-controls">
              <Field label="Canvas"><SelectInput value={thumbnailAspect} onChange={(event) => setThumbnailAspect(event.target.value as typeof thumbnailAspect)}><option value="16:9">YouTube landscape · 1280 × 720</option><option value="1:1">Square · 1080 × 1080</option><option value="9:16">Vertical · 1080 × 1920</option></SelectInput></Field>
              <Field label="Text position"><SelectInput value={thumbnailPosition} onChange={(event) => setThumbnailPosition(event.target.value as typeof thumbnailPosition)}><option value="top">Top</option><option value="center">Center</option><option value="bottom">Bottom</option></SelectInput></Field>
            </div>
            <div className="clipper-controls">
              <Field label="Text size"><TextInput max={140} min={18} onChange={(event) => setFontSize(Number(event.target.value))} type="number" value={fontSize} /></Field>
              <Field label="Text color"><TextInput onChange={(event) => setTextColor(event.target.value)} type="color" value={textColor} /></Field>
            </div>
            <div className="clipper-controls">
              <Field label={`Crop horizontal · ${Math.round(cropX * 100)}%`}><input aria-label="Crop horizontal position" className="range-input" max="1" min="0" onChange={(event) => setCropX(Number(event.target.value))} step="0.01" type="range" value={cropX} /></Field>
              <Field label={`Crop vertical · ${Math.round(cropY * 100)}%`}><input aria-label="Crop vertical position" className="range-input" max="1" min="0" onChange={(event) => setCropY(Number(event.target.value))} step="0.01" type="range" value={cropY} /></Field>
            </div>
            <Field label="Thumbnail text"><TextInput maxLength={200} onChange={(event) => setThumbnailText(event.target.value)} placeholder={title || "Enter thumbnail title"} value={thumbnailText} /></Field>
            {thumbnailPreview?.assetId === thumbnailAssetId ? <div className="thumbnail-placeholder"><Image alt="Rendered thumbnail preview" className="publishing-thumbnail-preview" height={720} src={thumbnailPreview.url} unoptimized width={1280} /></div> : <div className="thumbnail-placeholder"><ImageIcon size={28} /><strong>Local thumbnail preview</strong><span>Choose an image, then render the selected release title.</span></div>}
            <Button disabled={busy || !imageSourceId} icon={busy ? <LoaderCircle className="spin" size={15} /> : <ImageIcon size={15} />} onClick={() => void createThumbnail()} variant="primary">Render thumbnail</Button>
          </>
        ) : current === "Schedule" ? (
          <div className="release-list publishing-calendar">
            {calendar.map((publication) => (
              <button className="publishing-calendar-row" key={publication.id} onClick={() => { setProjectId(publication.project_id); applyPublication(publication); }} type="button">
                <CalendarDays size={16} />
                <span><strong>{publication.title}</strong><small>{publication.scheduled_at ? new Date(publication.scheduled_at).toLocaleString() : "No date planned"} · {publication.platform}</small></span>
                <Badge tone={publication.status === "published" ? "green" : publication.status === "scheduled" ? "cyan" : "neutral"}>{publication.status === "scheduled" ? "Planned locally" : publication.status}</Badge>
              </button>
            ))}
            {!calendar.length ? <span>No release packages on the calendar yet.</span> : null}
          </div>
        ) : current === "Analytics" ? (
          <>
            <div className="notice-strip"><Clock3 size={15} /><span>{capabilities?.youtube.reason ?? "Loading official publishing capability status."}</span></div>
            <div className="notice-strip"><Clock3 size={15} /><span>{capabilities?.analytics.reason ?? "Analytics are only shown when an authorized provider returns them."}</span></div>
            <p className="field-hint">Available official docs: {capabilities?.youtube.official_docs.map((url, index) => <span key={url}>{index ? " · " : ""}<a href={url} rel="noreferrer" target="_blank">{index ? "Upload guide" : "OAuth guide"}</a></span>)}</p>
            <div className="analytics-grid">{[["Views", "Unavailable"], ["Likes", "Unavailable"], ["Comments", "Unavailable"]].map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong><small>No provider-backed data</small></div>)}</div>
          </>
        ) : (
          <>
            <div className="clipper-controls">
              <Field label="Platform preset"><SelectInput value={platform} onChange={(event) => setPlatform(event.target.value as PublicationPlatform)}><option value="youtube">YouTube metadata limits</option><option value="instagram">Instagram draft</option><option value="tiktok">TikTok draft</option><option value="other">Other</option></SelectInput></Field>
              <Field label="Language"><TextInput maxLength={35} onChange={(event) => setLanguage(event.target.value)} placeholder="e.g. en" value={language} /></Field>
              <Field label="Category"><TextInput maxLength={100} onChange={(event) => setCategory(event.target.value)} placeholder="YouTube numeric category ID, e.g. 27" value={category} /></Field>
            </div>
            <Field label="Title"><TextInput maxLength={100} onChange={(event) => { setTitle(event.target.value); setThumbnailText(event.target.value); setTitleSuggestions([]); }} value={title} /><span className="field-counter">{title.length}/100</span></Field>
            <Button onClick={() => void createTitleSuggestions()} size="sm">Create rule-based title ideas</Button>
            {titleSuggestions.length ? <div className="publishing-title-suggestions">{titleSuggestions.map((suggestion) => <button key={suggestion} onClick={() => setTitle(suggestion)} type="button">{suggestion}</button>)}</div> : null}
            <p className="field-hint">Title ideas use local text templates, not an AI model or keyword-performance data.</p>
            <Field label="Description"><textarea className="text-area description-area" maxLength={5000} onChange={(event) => setDescription(event.target.value)} value={description} /><span className="field-counter">{description.length} characters · {new TextEncoder().encode(description).length}/5000 bytes</span></Field>
            <Field label="Tags · comma separated"><TextInput onChange={(event) => setTags(event.target.value)} value={tags} /><span className="field-counter">{splitList(tags).join("").length}/500 characters (YouTube limit)</span></Field>
            <div className="clipper-controls">
              <Field label="Hashtags · comma separated"><TextInput onChange={(event) => setHashtags(event.target.value)} value={hashtags} /></Field>
              <Field label="Primary keywords"><TextInput onChange={(event) => setPrimaryKeywords(event.target.value)} value={primaryKeywords} /></Field>
            </div>
            <Field label="Secondary keywords"><TextInput onChange={(event) => setSecondaryKeywords(event.target.value)} value={secondaryKeywords} /></Field>
            <Field label="Chapters · one per line (MM:SS Title)"><textarea className="text-area" onChange={(event) => setChapters(event.target.value)} placeholder={"00:00 Introduction\n01:25 Main topic"} value={chapters} /></Field>
            <div className="clipper-controls">
              <Field label="Video export"><SelectInput value={mediaAssetId} onChange={(event) => setMediaAssetId(event.target.value)}><option value="">No video selected</option>{videos.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}</SelectInput></Field>
              <Field label="Clip export"><SelectInput value={clipCandidateId} onChange={(event) => setClipCandidateId(event.target.value)}><option value="">No clip selected</option>{candidates.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.title || candidate.transcript_text?.slice(0, 40) || "Clip candidate"}</option>)}</SelectInput></Field>
              <Field label="Thumbnail"><SelectInput value={thumbnailAssetId} onChange={(event) => setThumbnailAssetId(event.target.value)}><option value="">No thumbnail selected</option>{images.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}</SelectInput></Field>
            </div>
            <div className="clipper-controls">
              <Field label="Status"><SelectInput value={entryStatus} onChange={(event) => setEntryStatus(event.target.value as typeof entryStatus)}><option value="draft">Draft</option><option value="ready">Ready</option><option value="scheduled">Scheduled locally</option></SelectInput></Field>
              {entryStatus === "scheduled" ? <Field label="Planned date"><TextInput min={new Date().toISOString().slice(0, 16)} onChange={(event) => setScheduledLocal(event.target.value)} type="datetime-local" value={scheduledLocal} /></Field> : null}
            </div>
            <div className="seo-score"><span><Check size={15} /> Local metadata checks</span><Badge tone="amber">No keyword metrics</Badge><small>No search volume, ranking, or performance claims are generated.</small></div>
            {revisionHistory.length ? <details className="publication-history"><summary>Version history · {revisionHistory.length} snapshots</summary>{revisionHistory.map((revision) => <div key={revision.id}><strong>Version {revision.version}</strong><small>{new Date(revision.created_at).toLocaleString()} · {String(revision.snapshot.title ?? "Untitled")}</small></div>)}</details> : null}
            <div className="form-action-row"><span>{selectedPublication ? `Version ${selectedPublication.version} · history retained` : "Creates a persistent local release package"}</span><Button disabled={busy} icon={busy ? <LoaderCircle className="spin" size={15} /> : undefined} onClick={() => void savePublication()} variant="primary">Save release package</Button></div>
          </>
        )}
        {error ? <p className="error-message" role="alert">{error}</p> : null}
      </Card>
      <Card className="workspace-aside-card">
        <SectionHeading title="Release readiness" description="The state is reported exactly as stored; scheduling is not publishing." />
        {current === "Thumbnail" && thumbnailPreview?.assetId === thumbnailAssetId ? <Image alt="Rendered thumbnail" className="publishing-thumbnail-preview" height={720} src={thumbnailPreview.url} unoptimized width={1280} /> : null}
        <div className="detail-list">
          <div><span>Project</span><strong>{projects.find((project) => project.id === projectId)?.name ?? "Select a project"}</strong></div>
          <div><span>Drafts</span><strong>{publications.length}</strong></div>
          <div><span>Local schedule</span><strong>{calendar.filter((item) => item.status === "scheduled").length} planned</strong></div>
          <div><span>YouTube publishing</span><strong>{capabilities?.youtube.available ? "Configured" : "Not configured"}</strong></div>
          <div><span>Analytics</span><strong>{capabilities?.analytics.available ? "Available after channel authorization" : "Unavailable"}</strong></div>
        </div>
        {current === "Schedule" ? <div className="notice-strip"><CalendarDays size={15} /><span>A scheduled entry is a local plan. It does not publish to a platform.</span></div> : null}
        {current === "Analytics" ? <div className="notice-strip"><Clock3 size={15} /><span>Metrics remain unavailable until a verified official account connection exists.</span></div> : null}
      </Card>
    </div>
  );
}
