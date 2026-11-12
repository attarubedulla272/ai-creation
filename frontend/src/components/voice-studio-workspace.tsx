"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import {
  AudioLines,
  Check,
  Download,
  FileAudio,
  LockKeyhole,
  Mic2,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Upload,
} from "lucide-react";
import { Badge, Button, Card, Field, SectionHeading, SelectInput, TextInput } from "@/components/ui";
import { useStudioUI } from "@/components/studio-shell";
import {
  authenticate,
  downloadMedia,
  listMedia,
  uploadMedia,
  type MediaAsset,
} from "@/lib/media-api";
import {
  listStudioProjects,
  type StudioProject,
} from "@/lib/timeline-api";
import {
  cancelVoiceJob,
  createDubbingProject,
  createVoiceConsent,
  createVoiceProfile,
  downloadVoiceSubtitles,
  getVoiceJob,
  getVoiceProviders,
  listTranscriptRevisions,
  listVoiceTranscripts,
  listDubbingProjects,
  listVoiceConsents,
  listVoiceProfiles,
  loadVoiceAudioPreview,
  queueDubbingSegmentTranslation,
  queueDubbingTranslation,
  queueDubbingExport,
  queueVoiceTranscription,
  regenerateDubbingSegment,
  revokeVoiceConsent,
  retryVoiceJob,
  updateDubbingProject,
  updateTranscriptSegment,
  type DubbingProject,
  type DubbingGlossaryTerm,
  type DubbingSegment,
  type TranscriptRevision,
  type VoiceConsent,
  type VoiceJob,
  type VoiceProfile,
  type VoiceProviders,
  type VoiceTranscript,
} from "@/lib/voice-api";

const TOKEN_KEY = "ai-creator-studio:media-token";
const LANGUAGES = [
  ["en", "English"],
  ["hi", "Hindi"],
  ["te", "Telugu"],
  ["ta", "Tamil"],
  ["kn", "Kannada"],
  ["ml", "Malayalam"],
  ["es", "Spanish"],
  ["fr", "French"],
  ["de", "German"],
  ["it", "Italian"],
  ["pt", "Portuguese"],
  ["ja", "Japanese"],
] as const;

function capabilityLabel(capability: { available: boolean; provider: string | null }) {
  return capability.available ? capability.provider ?? "Available" : "Not installed";
}

function formatTime(seconds: number) {
  const minutes = Math.floor(seconds / 60).toString().padStart(2, "0");
  const remainder = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${minutes}:${remainder}`;
}

export function VoiceStudioWorkspace({ current }: { current: string }) {
  const { notify } = useStudioUI();
  const [apiBase, setApiBase] = useState("http://localhost:8000");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState("");
  const [createAccount, setCreateAccount] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [providers, setProviders] = useState<VoiceProviders | null>(null);
  const [consents, setConsents] = useState<VoiceConsent[]>([]);
  const [profiles, setProfiles] = useState<VoiceProfile[]>([]);
  const [projects, setProjects] = useState<StudioProject[]>([]);
  const [assets, setAssets] = useState<MediaAsset[]>([]);
  const [transcripts, setTranscripts] = useState<VoiceTranscript[]>([]);
  const [transcriptRevisionState, setTranscriptRevisionState] = useState<{
    transcriptId: string;
    revisions: TranscriptRevision[];
  } | null>(null);
  const [dubbingProjects, setDubbingProjects] = useState<DubbingProject[]>([]);
  const [activeJob, setActiveJob] = useState<VoiceJob | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedMediaId, setSelectedMediaId] = useState("");
  const [selectedTranscriptId, setSelectedTranscriptId] = useState("");
  const [selectedDubbingId, setSelectedDubbingId] = useState("");
  const [selectedDubbingVideoId, setSelectedDubbingVideoId] = useState("");
  const [targetLanguage, setTargetLanguage] = useState("hi");
  const [sourceLanguage, setSourceLanguage] = useState("");
  const [consentBasis, setConsentBasis] = useState<VoiceConsent["authorization_basis"]>("self_attestation");
  const [profileName, setProfileName] = useState("");
  const [profileLanguage, setProfileLanguage] = useState("en");
  const [profileReferenceId, setProfileReferenceId] = useState("");
  const [attestAccepted, setAttestAccepted] = useState(false);
  const [script, setScript] = useState("");
  const [referenceAudioUrl, setReferenceAudioUrl] = useState("");
  const [uploading, setUploading] = useState(false);
  const [savingSegment, setSavingSegment] = useState("");
  const [savingDubbing, setSavingDubbing] = useState(false);
  const [glossarySource, setGlossarySource] = useState("");
  const [glossaryTranslation, setGlossaryTranslation] = useState("");
  const [glossaryNotes, setGlossaryNotes] = useState("");
  const [segmentAudioUrl, setSegmentAudioUrl] = useState("");
  const [transcriptPreview, setTranscriptPreview] = useState<{ assetId: string; url: string } | null>(null);

  const selectedTranscript = transcripts.find((item) => item.id === selectedTranscriptId) ?? null;
  const selectedDubbing = dubbingProjects.find((item) => item.id === selectedDubbingId) ?? null;
  const transcriptSource = assets.find((asset) => asset.id === selectedTranscript?.media_asset_id) ?? null;
  const transcriptRevisions = transcriptRevisionState?.transcriptId === selectedTranscriptId
    ? transcriptRevisionState.revisions
    : [];
  const audioAssets = useMemo(() => assets.filter((asset) => asset.media_type === "audio"), [assets]);
  const videoAssets = useMemo(() => assets.filter((asset) => asset.media_type === "video"), [assets]);
  const transcriptionSources = useMemo(
    () => assets.filter((asset) => asset.media_type === "audio"
      || (asset.media_type === "video" && Boolean(asset.metadata_json?.derivatives?.extracted_audio))),
    [assets],
  );
  const activeConsents = consents.filter((consent) => !consent.revoked_at);

  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (active) setToken(window.sessionStorage.getItem(TOKEN_KEY) ?? "");
    });
    return () => {
      active = false;
    };
  }, []);

  const refreshWorkspace = useCallback(async () => {
    if (!token) return;
    const [
      providerStatus,
      consentRecords,
      voiceProfiles,
      studioProjects,
      mediaAssets,
      savedTranscripts,
      savedDubbingProjects,
    ] = await Promise.all([
      getVoiceProviders(apiBase, token),
      listVoiceConsents(apiBase, token),
      listVoiceProfiles(apiBase, token),
      listStudioProjects(apiBase, token),
      listMedia(apiBase, token),
      listVoiceTranscripts(apiBase, token),
      listDubbingProjects(apiBase, token),
    ]);
    setProviders(providerStatus);
    setConsents(consentRecords);
    setProfiles(voiceProfiles);
    setProjects(studioProjects);
    setAssets(mediaAssets);
    setTranscripts(savedTranscripts);
    setDubbingProjects(savedDubbingProjects);
    setSelectedProjectId((current) => current || studioProjects[0]?.id || "");
    setSelectedMediaId((current) => current || mediaAssets.find((asset) => asset.media_type === "audio")?.id || "");
    setSelectedTranscriptId((current) => (
      savedTranscripts.some((transcript) => transcript.id === current)
        ? current
        : savedTranscripts[0]?.id ?? ""
    ));
    setSelectedDubbingId((current) => (
      savedDubbingProjects.some((item) => item.id === current)
        ? current
        : savedDubbingProjects[0]?.id ?? ""
    ));
    setError("");
  }, [apiBase, token]);

  useEffect(() => {
    if (!token) return;
    let active = true;
    void Promise.resolve().then(() => {
      if (!active) return;
      return refreshWorkspace().catch((loadError: unknown) => {
        if (active) setError(loadError instanceof Error ? loadError.message : "Could not load Voice Studio data.");
      });
    });
    return () => {
      active = false;
    };
  }, [refreshWorkspace, token]);

  useEffect(() => {
    if (!selectedTranscriptId || !token) return;
    let active = true;
    void listTranscriptRevisions(apiBase, token, selectedTranscriptId)
      .then((revisions) => {
        if (active) setTranscriptRevisionState({ transcriptId: selectedTranscriptId, revisions });
      })
      .catch((revisionError: unknown) => {
        if (active) {
          setError(
            revisionError instanceof Error
              ? revisionError.message
              : "Could not load transcript revisions.",
          );
        }
      });
    return () => {
      active = false;
    };
  }, [apiBase, selectedTranscriptId, token]);

  useEffect(() => {
    if (!activeJob || activeJob.status === "completed" || activeJob.status === "failed" || activeJob.status === "cancelled") {
      return;
    }
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const updated = await getVoiceJob(apiBase, token, activeJob.id);
        if (!active) return;
        setActiveJob(updated);
        if (updated.status === "completed") {
          if (updated.output_data?.transcript_id) {
            const transcript = await listVoiceTranscripts(apiBase, token);
            if (active) {
              setTranscripts(transcript);
              setSelectedTranscriptId(updated.output_data.transcript_id);
              notify("Transcription completed and saved.");
            }
          } else if (updated.output_data?.media_asset_id) {
            notify("User-supplied audio segments were assembled and saved to the media library.");
            void refreshWorkspace();
          } else if (updated.job_type === "voice_translation") {
            await refreshWorkspace();
            notify("Local translation finished. Review each segment before approving it.");
          }
        } else if (updated.status === "failed" && updated.error_message) {
          setError(updated.error_message);
        } else if (active) {
          timer = setTimeout(poll, 800);
        }
      } catch (pollError) {
        if (active) setError(pollError instanceof Error ? pollError.message : "Could not refresh job progress.");
      }
    };
    timer = setTimeout(poll, 500);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [activeJob, apiBase, notify, refreshWorkspace, token]);

  useEffect(() => {
    return () => {
      if (referenceAudioUrl) URL.revokeObjectURL(referenceAudioUrl);
      if (segmentAudioUrl) URL.revokeObjectURL(segmentAudioUrl);
      if (transcriptPreview) URL.revokeObjectURL(transcriptPreview.url);
    };
  }, [referenceAudioUrl, segmentAudioUrl, transcriptPreview]);

  async function connectAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const accessToken = await authenticate(apiBase, email, password, createAccount);
      window.sessionStorage.setItem(TOKEN_KEY, accessToken);
      setToken(accessToken);
      setPassword("");
      notify(createAccount ? "Account created and connected." : "Connected to the backend.");
    } catch (connectError) {
      setError(connectError instanceof Error ? connectError.message : "Could not connect to the backend.");
    } finally {
      setBusy(false);
    }
  }

  function disconnect() {
    window.sessionStorage.removeItem(TOKEN_KEY);
    setToken("");
    setProviders(null);
    setProfiles([]);
    setAssets([]);
    setTranscripts([]);
    setTranscriptRevisionState(null);
    setDubbingProjects([]);
    setActiveJob(null);
    setError("");
  }

  async function uploadReference(file: File | undefined) {
    if (!file || !token) return;
    setUploading(true);
    setError("");
    try {
      const uploaded = await uploadMedia(apiBase, token, file, () => undefined);
      setAssets((currentAssets) => [uploaded.asset, ...currentAssets.filter((item) => item.id !== uploaded.asset.id)]);
      setProfileReferenceId(uploaded.asset.id);
      notify("Audio reference uploaded to your local media library.");
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "Could not upload the reference audio.");
    } finally {
      setUploading(false);
    }
  }

  async function saveVoiceProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!attestAccepted || !profileReferenceId || !activeConsents[0]) return;
    setBusy(true);
    setError("");
    try {
      const profile = await createVoiceProfile(apiBase, token, {
        name: profileName,
        language: profileLanguage,
        consent_id: activeConsents[0].id,
        reference_asset_id: profileReferenceId,
      });
      setProfiles((currentProfiles) => [profile, ...currentProfiles]);
      setProfileName("");
      setAttestAccepted(false);
      notify("Authorized voice reference saved. No clone or voice model was created.");
    } catch (profileError) {
      setError(profileError instanceof Error ? profileError.message : "Could not save the voice reference.");
    } finally {
      setBusy(false);
    }
  }

  async function grantConsent() {
    setBusy(true);
    setError("");
    try {
      const consent = await createVoiceConsent(apiBase, token, consentBasis);
      setConsents((currentConsents) => [consent, ...currentConsents]);
      setAttestAccepted(false);
      notify("Authorization attestation recorded.");
    } catch (consentError) {
      setError(consentError instanceof Error ? consentError.message : "Could not record authorization.");
    } finally {
      setBusy(false);
    }
  }

  async function revokeConsent(consentId: string) {
    setBusy(true);
    setError("");
    try {
      const consent = await revokeVoiceConsent(apiBase, token, consentId);
      setConsents((currentConsents) => currentConsents.map((item) => item.id === consent.id ? consent : item));
      setProfiles(await listVoiceProfiles(apiBase, token));
      notify("Authorization revoked; the associated profile is no longer available for assignment.");
    } catch (revokeError) {
      setError(revokeError instanceof Error ? revokeError.message : "Could not revoke authorization.");
    } finally {
      setBusy(false);
    }
  }

  async function beginTranscription(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const job = await queueVoiceTranscription(apiBase, token, {
        project_id: selectedProjectId,
        media_asset_id: selectedMediaId,
        ...(sourceLanguage ? { language: sourceLanguage } : {}),
      });
      setActiveJob(job);
      notify("Local transcription queued.");
    } catch (queueError) {
      setError(queueError instanceof Error ? queueError.message : "Could not queue transcription.");
    } finally {
      setBusy(false);
    }
  }

  async function saveSourceSegment(segmentId: string, text: string, speakerLabel: string, translatedText: string) {
    if (!selectedTranscript) return;
    setSavingSegment(segmentId);
    setError("");
    try {
      const updated = await updateTranscriptSegment(apiBase, token, selectedTranscript.id, segmentId, {
        text,
        speaker_label: speakerLabel || null,
        translated_text: translatedText || null,
      });
      setTranscripts((currentTranscripts) => currentTranscripts.map((item) => (
        item.id === updated.id ? updated : item
      )));
      const revisions = await listTranscriptRevisions(apiBase, token, selectedTranscript.id);
      setTranscriptRevisionState({ transcriptId: selectedTranscript.id, revisions });
      notify("Transcript segment saved.");
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Could not save the transcript segment.");
    } finally {
      setSavingSegment("");
    }
  }

  async function startDubbingPlan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedTranscriptId) return;
    setBusy(true);
    setError("");
    try {
      const created = await createDubbingProject(apiBase, token, selectedTranscriptId, targetLanguage);
      setDubbingProjects((currentProjects) => [created, ...currentProjects]);
      setSelectedDubbingId(created.id);
      setSelectedDubbingVideoId("");
      notify("Dubbing plan saved. Translation and speech are not generated automatically.");
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "Could not create the dubbing plan.");
    } finally {
      setBusy(false);
    }
  }

  function changeDubbingSegment(segmentId: string, patch: Partial<DubbingSegment>) {
    if (!selectedDubbing) return;
    const updated = {
      ...selectedDubbing,
      segments_data: selectedDubbing.segments_data.map((segment) => (
        segment.id === segmentId ? { ...segment, ...patch } : segment
      )),
    };
    setDubbingProjects((currentProjects) => currentProjects.map((item) => (
      item.id === updated.id ? updated : item
    )));
  }

  async function saveDubbingPlan() {
    if (!selectedDubbing) return;
    setSavingDubbing(true);
    setError("");
    try {
      const updated = await updateDubbingProject(
        apiBase,
        token,
        selectedDubbing.id,
        selectedDubbing.segments_data,
        selectedDubbing.glossary,
      );
      setDubbingProjects((currentProjects) => currentProjects.map((item) => (
        item.id === updated.id ? updated : item
      )));
      notify("Dubbing plan saved.");
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Could not save the dubbing plan.");
    } finally {
      setSavingDubbing(false);
    }
  }

  async function queueAutomaticTranslation(regenerateExisting = false) {
    if (!selectedDubbing) return;
    setBusy(true);
    setError("");
    try {
      const job = await queueDubbingTranslation(
        apiBase,
        token,
        selectedDubbing.id,
        regenerateExisting,
      );
      setActiveJob(job);
      notify(regenerateExisting ? "Full translation regeneration queued." : "Missing translations queued.");
    } catch (translationError) {
      setError(translationError instanceof Error ? translationError.message : "Could not queue translation.");
    } finally {
      setBusy(false);
    }
  }

  async function queueSegmentTranslation(segmentId: string) {
    if (!selectedDubbing) return;
    setBusy(true);
    setError("");
    try {
      const job = await queueDubbingSegmentTranslation(apiBase, token, selectedDubbing.id, segmentId);
      setActiveJob(job);
      notify("Segment regeneration queued.");
    } catch (translationError) {
      setError(translationError instanceof Error ? translationError.message : "Could not queue segment translation.");
    } finally {
      setBusy(false);
    }
  }

  async function queueDubbingAudioExport() {
    if (!selectedDubbing) return;
    setBusy(true);
    setError("");
    try {
      const job = await queueDubbingExport(
        apiBase,
        token,
        selectedDubbing.id,
        selectedDubbingVideoId || undefined,
      );
      setActiveJob(job);
      notify("FFmpeg audio assembly queued. No speech will be synthesized.");
    } catch (exportError) {
      setError(exportError instanceof Error ? exportError.message : "Could not queue audio assembly.");
    } finally {
      setBusy(false);
    }
  }

  async function listenToReference(assetId: string) {
    setError("");
    try {
      const url = await loadVoiceAudioPreview(apiBase, token, assetId);
      if (referenceAudioUrl) URL.revokeObjectURL(referenceAudioUrl);
      setReferenceAudioUrl(url);
    } catch (previewError) {
      setError(previewError instanceof Error ? previewError.message : "Could not play the reference audio.");
    }
  }

  async function listenToSegmentAudio(assetId: string) {
    setError("");
    try {
      const url = await loadVoiceAudioPreview(apiBase, token, assetId);
      if (segmentAudioUrl) URL.revokeObjectURL(segmentAudioUrl);
      setSegmentAudioUrl(url);
    } catch (previewError) {
      setError(previewError instanceof Error ? previewError.message : "Could not preview attached audio.");
    }
  }

  async function listenToTranscriptSource(assetId: string) {
    setError("");
    try {
      const url = await loadVoiceAudioPreview(apiBase, token, assetId);
      setTranscriptPreview({ assetId, url });
    } catch (previewError) {
      setError(previewError instanceof Error ? previewError.message : "Could not preview the transcript source.");
    }
  }

  function changeDubbingGlossary(glossary: DubbingGlossaryTerm[]) {
    if (!selectedDubbing) return;
    const updated = { ...selectedDubbing, glossary };
    setDubbingProjects((currentProjects) => currentProjects.map((item) => (
      item.id === updated.id ? updated : item
    )));
  }

  function addGlossaryTerm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedDubbing || !glossarySource.trim() || !glossaryTranslation.trim()) return;
    changeDubbingGlossary([
      ...selectedDubbing.glossary,
      {
        source: glossarySource.trim(),
        translation: glossaryTranslation.trim(),
        ...(glossaryNotes.trim() ? { notes: glossaryNotes.trim() } : {}),
      },
    ]);
    setGlossarySource("");
    setGlossaryTranslation("");
    setGlossaryNotes("");
  }

  async function downloadSubtitles(path: string, filename: string) {
    try {
      await downloadVoiceSubtitles(apiBase, token, path, filename);
    } catch (subtitleError) {
      setError(subtitleError instanceof Error ? subtitleError.message : "Could not export subtitles.");
    }
  }

  async function downloadAssembledOutput(assetId: string) {
    try {
      await downloadMedia(apiBase, token, assetId);
    } catch (downloadError) {
      setError(downloadError instanceof Error ? downloadError.message : "Could not download the exported media.");
    }
  }

  async function regenerateSegment(dubbingProjectId: string, segmentId: string) {
    try {
      await regenerateDubbingSegment(apiBase, token, dubbingProjectId, segmentId);
    } catch (regenerationError) {
      setError(regenerationError instanceof Error ? regenerationError.message : "Could not regenerate this segment.");
    }
  }

  if (!token) {
    return (
      <Card className="voice-connect-card">
        <SectionHeading
          title="Connect your local backend"
          description="Voice projects and consent records are stored in your configured backend."
          action={<Badge tone="cyan">Local-first</Badge>}
        />
        <form className="voice-connect-form" onSubmit={(event) => void connectAccount(event)}>
          <Field label="Backend URL">
            <TextInput onChange={(event) => setApiBase(event.target.value)} value={apiBase} />
          </Field>
          <Field label="Email">
            <TextInput autoComplete="email" onChange={(event) => setEmail(event.target.value)} required type="email" value={email} />
          </Field>
          <Field label="Password">
            <TextInput autoComplete={createAccount ? "new-password" : "current-password"} onChange={(event) => setPassword(event.target.value)} required type="password" value={password} />
          </Field>
          <label className="voice-checkbox"><input checked={createAccount} onChange={(event) => setCreateAccount(event.target.checked)} type="checkbox" /> Create a new account</label>
          <Button disabled={busy} type="submit" variant="primary">{busy ? "Connecting…" : "Connect Voice Studio"}</Button>
        </form>
        {error ? <p className="voice-error" role="alert">{error}</p> : null}
      </Card>
    );
  }

  if (!providers) {
    return (
      <Card className="voice-connect-card">
        <div className="voice-loading"><RefreshCw aria-hidden="true" size={16} /> Loading Voice Studio data…</div>
        {error ? <p className="voice-error" role="alert">{error}</p> : null}
        <Button onClick={disconnect}>Disconnect account</Button>
      </Card>
    );
  }

  return (
    <div className="voice-studio-workspace">
      <div className="voice-workspace-toolbar">
        <div>
          <div className="eyebrow">LOCAL WORKSPACE</div>
          <strong>Provider-backed voice tools</strong>
        </div>
        <div className="voice-toolbar-actions">
          <Button onClick={() => void refreshWorkspace()} size="sm" icon={<RefreshCw size={14} />}>Refresh</Button>
          <Button onClick={disconnect} size="sm" variant="ghost">Disconnect</Button>
        </div>
      </div>

      <div className="voice-capability-grid" aria-label="Provider availability">
        {[
          ["Transcription", providers.transcription],
          ["Translation", providers.translation],
          ["Text to speech", providers.text_to_speech],
          ["Speaker detection", providers.speaker_diarization],
        ].map(([label, capability]) => {
          const item = capability as { available: boolean; provider: string | null };
          return (
            <div className="voice-capability" key={label as string}>
              <span className={item.available ? "voice-capability-dot available" : "voice-capability-dot"} />
              <span><strong>{label as string}</strong><small>{capabilityLabel(item)}</small></span>
            </div>
          );
        })}
      </div>

      {error ? <div className="voice-error" role="alert">{error}</div> : null}
      {activeJob ? (
        <div aria-live="polite" className={`voice-job-status voice-job-${activeJob.status}`}>
          <span>
            {activeJob.job_type === "voice_transcription"
              ? "Transcription"
              : activeJob.job_type === "voice_translation"
                ? "Translation"
                : "Audio assembly"} · {activeJob.status}
          </span>
          <progress max={100} value={activeJob.progress} />
          <strong>{activeJob.progress}%</strong>
          {["queued", "processing"].includes(activeJob.status) ? (
            <Button
              onClick={() => void cancelVoiceJob(apiBase, token, activeJob.id)
                .then(setActiveJob)
                .catch((cancelError: unknown) => setError(
                  cancelError instanceof Error ? cancelError.message : "Could not cancel the job.",
                ))}
              size="sm"
              variant="ghost"
            >
              Cancel
            </Button>
          ) : null}
          {activeJob.job_type === "voice_translation" && activeJob.status === "failed" ? (
            <Button
              onClick={() => void retryVoiceJob(apiBase, token, activeJob.id)
                .then(setActiveJob)
                .catch((retryError: unknown) => setError(
                  retryError instanceof Error ? retryError.message : "Could not retry translation.",
                ))}
              size="sm"
              variant="secondary"
            >
              Retry failed segments
            </Button>
          ) : null}
          {activeJob.status === "completed" && activeJob.output_data?.media_asset_id ? (
            <Button
              onClick={() => {
                const assetId = activeJob.output_data?.media_asset_id;
                if (assetId) void downloadAssembledOutput(assetId);
              }}
              size="sm"
              icon={<Download size={14} />}
            >
              Download assembled audio
            </Button>
          ) : null}
          {activeJob.status === "completed" && activeJob.output_data?.video_asset_id ? (
            <Button
              onClick={() => {
                const assetId = activeJob.output_data?.video_asset_id;
                if (assetId) void downloadAssembledOutput(assetId);
              }}
              size="sm"
              icon={<Download size={14} />}
            >
              Download dubbed MP4
            </Button>
          ) : null}
        </div>
      ) : null}

      {current === "Voice library" ? (
        <div className="voice-content-grid">
          <Card className="workspace-main-card">
            <SectionHeading
              title="Authorized voice references"
              description="Profiles store an audio reference and user attestation only; no voice model is created."
              action={<Badge tone="amber">Reference only</Badge>}
            />
            <div className="voice-profile-list">
              {profiles.length ? profiles.map((profile) => (
                <article className="voice-profile-card" key={profile.id}>
                  <span className="voice-profile-icon"><Mic2 size={17} /></span>
                  <div className="voice-profile-details">
                    <strong>{profile.name}</strong>
                    <small>{LANGUAGES.find(([code]) => code === profile.language)?.[1] ?? profile.language ?? "Language not set"} · reference recording saved</small>
                  </div>
                  <Badge tone="violet">Authorized reference</Badge>
                  {profile.reference_asset_id ? (
                    <Button onClick={() => void listenToReference(profile.reference_asset_id!)} size="sm">Listen to reference</Button>
                  ) : null}
                </article>
              )) : <p className="voice-empty">No voice references have been added to this account.</p>}
            </div>
            {referenceAudioUrl ? <audio className="voice-reference-player" controls src={referenceAudioUrl} /> : null}
            <div className="voice-consent-records">
              <SectionHeading title="Consent records" description="Authorization is a user attestation, not independently verified." />
              {consents.map((consent) => (
                <div className="voice-consent-row" key={consent.id}>
                  <span><ShieldCheck size={15} />{consent.authorization_basis === "self_attestation" ? "Self" : "Authorized person"} · {consent.revoked_at ? "revoked" : "active"}</span>
                  {!consent.revoked_at ? (
                    <Button disabled={busy} onClick={() => void revokeConsent(consent.id)} size="sm" variant="danger">Revoke</Button>
                  ) : null}
                </div>
              ))}
              <div className="voice-consent-controls">
                <SelectInput aria-label="Authorization basis" onChange={(event) => setConsentBasis(event.target.value as VoiceConsent["authorization_basis"])} value={consentBasis}>
                  <option value="self_attestation">My own voice</option>
                  <option value="authorized_person">I have the person&apos;s permission</option>
                </SelectInput>
                <Button disabled={busy || !attestAccepted} onClick={() => void grantConsent()} icon={<ShieldCheck size={14} />}>Record consent attestation</Button>
              </div>
            </div>
          </Card>

          <Card className="workspace-aside-card">
            <SectionHeading title="Add a reference" description="Upload an audio sample you own or are authorized to use." />
            <form className="voice-form" onSubmit={(event) => void saveVoiceProfile(event)}>
              <Field label="Profile name"><TextInput onChange={(event) => setProfileName(event.target.value)} required value={profileName} /></Field>
              <Field label="Reference language">
                <SelectInput onChange={(event) => setProfileLanguage(event.target.value)} value={profileLanguage}>
                  {LANGUAGES.map(([code, name]) => <option key={code} value={code}>{name}</option>)}
                </SelectInput>
              </Field>
              <Field label="Audio reference">
                <SelectInput onChange={(event) => setProfileReferenceId(event.target.value)} value={profileReferenceId}>
                  <option value="">Select an owned audio file</option>
                  {audioAssets.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}
                </SelectInput>
              </Field>
              <label className="voice-upload-button">
                <Upload size={15} /> {uploading ? "Uploading…" : "Upload audio reference"}
                <input accept="audio/*" disabled={uploading} onChange={(event) => void uploadReference(event.target.files?.[0])} type="file" />
              </label>
              <label className="voice-checkbox">
                <input checked={attestAccepted} onChange={(event) => setAttestAccepted(event.target.checked)} type="checkbox" />
                I affirm that I own this voice or have permission to store and use this recording.
              </label>
              <p className="field-hint">The checkbox records your attestation; the service does not independently verify identity or permission.</p>
              <Button disabled={busy || !attestAccepted || !activeConsents.length || !profileReferenceId} type="submit" variant="primary">
                Save authorized reference
              </Button>
            </form>
          </Card>
        </div>
      ) : null}

      {current === "Transcription" ? (
        <div className="voice-content-grid">
          <Card className="workspace-main-card">
            <SectionHeading title="Audio transcription" description="Native MLX Whisper runs on supported Apple Silicon macOS; each request is queued in the background." />
            <form className="voice-transcription-form" onSubmit={(event) => void beginTranscription(event)}>
              <Field label="Project">
                <SelectInput onChange={(event) => setSelectedProjectId(event.target.value)} required value={selectedProjectId}>
                  <option value="">Select a project</option>
                  {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
                </SelectInput>
              </Field>
              <Field label="Audio or processed video">
                <SelectInput onChange={(event) => setSelectedMediaId(event.target.value)} required value={selectedMediaId}>
                  <option value="">Select owned media</option>
                  {transcriptionSources.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}{asset.media_type === "video" ? " · extracted audio" : ""}</option>)}
                </SelectInput>
              </Field>
              <Field label="Language">
                <SelectInput onChange={(event) => setSourceLanguage(event.target.value)} value={sourceLanguage}>
                  <option value="">Auto-detect</option>
                  {LANGUAGES.map(([code, name]) => <option key={code} value={code}>{name}</option>)}
                </SelectInput>
              </Field>
              <Button disabled={!providers.transcription.available || busy || !selectedProjectId || !selectedMediaId} type="submit" variant="primary" icon={<AudioLines size={15} />}>
                {providers.transcription.available ? "Transcribe audio" : "Transcription provider unavailable"}
              </Button>
            </form>
            {!providers.transcription.available ? (
              <div className="voice-notice"><LockKeyhole size={15} /><span>On this computer install with <code>uv sync --extra dev --extra voice-mlx</code>. No audio is sent to a paid API.</span></div>
            ) : null}
            <div className="voice-transcript-editor">
              <SectionHeading
                title="Saved transcripts"
                description={selectedTranscript ? `Language: ${selectedTranscript.language ?? "not reported"} · ${selectedTranscript.segments.length} timed segments` : "Transcribed text will appear here after a local job completes."}
                action={selectedTranscript ? (
                  <div className="voice-inline-actions">
                    {selectedTranscript.media_asset_id && transcriptSource ? (
                      <Button onClick={() => void listenToTranscriptSource(selectedTranscript.media_asset_id!)} size="sm">Preview original</Button>
                    ) : null}
                    <Button onClick={() => void downloadSubtitles(`/voice/transcripts/${selectedTranscript.id}/subtitles/srt`, "transcript.srt")} size="sm" icon={<Download size={13} />}>SRT</Button>
                    <Button onClick={() => void downloadSubtitles(`/voice/transcripts/${selectedTranscript.id}/subtitles/vtt`, "transcript.vtt")} size="sm" icon={<Download size={13} />}>VTT</Button>
                  </div>
                ) : null}
              />
              {transcripts.length ? (
                <SelectInput aria-label="Choose a saved transcript" onChange={(event) => setSelectedTranscriptId(event.target.value)} value={selectedTranscriptId}>
                  {transcripts.map((item) => <option key={item.id} value={item.id}>{new Date(item.created_at).toLocaleString()} · {item.segments.length} segments</option>)}
                </SelectInput>
              ) : null}
              {transcriptPreview && transcriptPreview.assetId === transcriptSource?.id ? (
                transcriptSource.media_type === "video"
                  ? <video className="voice-reference-player" controls playsInline src={transcriptPreview.url} />
                  : <audio className="voice-reference-player" controls src={transcriptPreview.url} />
              ) : null}
              {selectedTranscript?.segments.map((segment) => (
                <TranscriptSegmentEditor
                  key={`${segment.id}:${segment.text}:${segment.speaker_label ?? ""}:${segment.translated_text ?? ""}`}
                  saving={savingSegment === segment.id}
                  segment={segment}
                  onSave={(text, speaker, translation) => void saveSourceSegment(segment.id, text, speaker, translation)}
                />
              ))}
              {transcriptRevisions.length ? (
                <details className="voice-revision-list">
                  <summary>Revision history ({transcriptRevisions.length})</summary>
                  {transcriptRevisions.map((revision) => (
                    <details key={revision.id}>
                      <summary>Revision {revision.revision_number} · {new Date(revision.created_at).toLocaleString()} · {revision.snapshot.length} segments</summary>
                      <div className="voice-revision-snapshot">
                        {revision.snapshot.map((segment) => (
                          <p key={segment.id}>
                            <strong>{formatTime(segment.start_seconds)}–{formatTime(segment.end_seconds)}</strong>
                            {segment.speaker_label ? ` · ${segment.speaker_label}` : ""} · {segment.text}
                          </p>
                        ))}
                      </div>
                    </details>
                  ))}
                </details>
              ) : null}
            </div>
            <div className="voice-notice"><Mic2 size={15} /><span>Speaker diarization is not installed. Speaker labels can be edited manually after transcription.</span></div>
          </Card>
          <ProviderPanel providers={providers} />
        </div>
      ) : null}

      {current === "Dubbing" ? (
        <div className="voice-content-grid">
          <Card className="workspace-main-card">
            <SectionHeading title="Multilingual dubbing workspace" description="Automatic translation uses an optional local worker. Candidate language quality is not verified yet; review output before approval. Speech generation is not available." />
            <form className="voice-dubbing-create" onSubmit={(event) => void startDubbingPlan(event)}>
              <Field label="Source transcript">
                <SelectInput onChange={(event) => setSelectedTranscriptId(event.target.value)} required value={selectedTranscriptId}>
                  <option value="">Select a saved transcript</option>
                  {transcripts.map((item) => <option key={item.id} value={item.id}>{new Date(item.created_at).toLocaleString()} · {item.segments.length} segments</option>)}
                </SelectInput>
              </Field>
              <Field label="Target language">
                <SelectInput onChange={(event) => setTargetLanguage(event.target.value)} value={targetLanguage}>
                  {LANGUAGES.map(([code, name]) => <option key={code} value={code}>{name}</option>)}
                </SelectInput>
              </Field>
              <Button disabled={busy || !selectedTranscriptId} type="submit" icon={<Sparkles size={14} />}>Create dubbing plan</Button>
            </form>
            {dubbingProjects.length ? (
              <SelectInput aria-label="Choose a saved dubbing plan" onChange={(event) => {
                setSelectedDubbingId(event.target.value);
                setSelectedDubbingVideoId("");
              }} value={selectedDubbingId}>
                {dubbingProjects.map((item) => <option key={item.id} value={item.id}>{LANGUAGES.find(([code]) => code === item.target_language)?.[1] ?? item.target_language} · {new Date(item.created_at).toLocaleString()}</option>)}
              </SelectInput>
            ) : <p className="voice-empty">Create a plan from a saved transcript to begin editing translations and timing.</p>}
            {selectedDubbing ? (
              <>
                <div className="voice-glossary">
                  <SectionHeading title="Project glossary" description="Keep names and technical terms consistent in manually edited translations." />
                  <form className="voice-glossary-form" onSubmit={(event) => addGlossaryTerm(event)}>
                    <TextInput aria-label="Glossary source term" onChange={(event) => setGlossarySource(event.target.value)} placeholder="Source term" value={glossarySource} />
                    <TextInput aria-label="Glossary translation" onChange={(event) => setGlossaryTranslation(event.target.value)} placeholder="Preferred translation" value={glossaryTranslation} />
                    <TextInput aria-label="Glossary notes" onChange={(event) => setGlossaryNotes(event.target.value)} placeholder="Notes (optional)" value={glossaryNotes} />
                    <Button type="submit" size="sm">Add term</Button>
                  </form>
                  {selectedDubbing.glossary.map((term, index) => (
                    <div className="voice-glossary-term" key={`${term.source}-${index}`}>
                      <span><strong>{term.source}</strong> → {term.translation}{term.notes ? ` · ${term.notes}` : ""}</span>
                      <Button
                        onClick={() => changeDubbingGlossary(selectedDubbing.glossary.filter((_, itemIndex) => itemIndex !== index))}
                        size="sm"
                        variant="ghost"
                      >
                        Remove
                      </Button>
                    </div>
                  ))}
                </div>
                <div className="voice-segment-approval">
                  <Button
                    disabled={busy || !providers?.translation.available}
                    onClick={() => void queueAutomaticTranslation()}
                    size="sm"
                    icon={<Sparkles size={14} />}
                  >
                    Translate missing segments
                  </Button>
                  <Button
                    disabled={busy || !providers?.translation.available}
                    onClick={() => void queueAutomaticTranslation(true)}
                    size="sm"
                    variant="secondary"
                  >
                    Regenerate all translations
                  </Button>
                  {!providers?.translation.available ? (
                    <span className="field-hint">Configure the isolated translation worker to enable automatic translation.</span>
                  ) : (
                    <span className="field-hint">
                      Candidates: English, Hindi, Telugu, Tamil, Kannada and Malayalam. Results are not language-verified yet.
                    </span>
                  )}
                </div>
                <div className="voice-dubbing-segments">
                  {selectedDubbing.segments_data.map((segment) => (
                    <article className="voice-dubbing-segment" key={segment.id}>
                      <div className="voice-segment-heading">
                        <span className="timestamp">{formatTime(segment.start_seconds)}</span>
                        <strong>Segment {segment.order_index + 1}</strong>
                        <Badge>{segment.audio_source === "user_supplied" ? "User audio" : "No audio"}</Badge>
                      </div>
                      <div className="voice-source-text">{segment.source_text}</div>
                      <Field label="Translation (editable · source text remains unchanged)">
                        <textarea
                          className="text-area"
                          onChange={(event) => changeDubbingSegment(segment.id, {
                            translated_text: event.target.value,
                            translation_status: event.target.value.trim() ? "manual" : "not_translated",
                            translation_approved: false,
                          })}
                          value={segment.translated_text}
                        />
                      </Field>
                      <div className="voice-segment-approval">
                        <Badge tone={
                          segment.translation_status === "completed"
                            ? "cyan"
                            : segment.translation_status === "failed"
                              ? "amber"
                              : "violet"
                        }>
                          {(segment.translation_status ?? (
                            segment.translated_text ? "manual" : "not_translated"
                          )).replaceAll("_", " ")}
                        </Badge>
                        {segment.translation_provider ? (
                          <span className="field-hint">
                            {segment.translation_provider} · {segment.translation_model} · {segment.translation_model_version}
                          </span>
                        ) : null}
                        {segment.translation_error ? <span className="field-hint">{segment.translation_error}</span> : null}
                        <Button
                          disabled={busy || !providers?.translation.available}
                          onClick={() => void queueSegmentTranslation(segment.id)}
                          size="sm"
                          variant="ghost"
                        >
                          Regenerate segment
                        </Button>
                      </div>
                      <div className="voice-segment-approval">
                        <Button
                          disabled={!segment.translated_text.trim()}
                          onClick={() => changeDubbingSegment(segment.id, { translation_approved: !segment.translation_approved })}
                          size="sm"
                        >
                          {segment.translation_approved ? "Translation approved" : "Approve translation"}
                        </Button>
                        <Badge tone={segment.translation_approved ? "cyan" : "amber"}>
                          {segment.translation_approved ? "Approved" : "Needs review"}
                        </Badge>
                      </div>
                      <div className="voice-segment-controls">
                        <Field label="Authorized voice reference">
                          <SelectInput onChange={(event) => changeDubbingSegment(segment.id, { voice_profile_id: event.target.value || null })} value={segment.voice_profile_id ?? ""}>
                            <option value="">Not assigned</option>
                            {profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}
                          </SelectInput>
                        </Field>
                        <Field label="Source time in seconds">
                          <div className="voice-time-fields">
                            <TextInput aria-label="Segment start in seconds" min="0" onChange={(event) => changeDubbingSegment(segment.id, { start_seconds: Number(event.target.value) })} step="0.01" type="number" value={segment.start_seconds} />
                            <TextInput aria-label="Segment end in seconds" min="0.01" onChange={(event) => changeDubbingSegment(segment.id, { end_seconds: Number(event.target.value) })} step="0.01" type="number" value={segment.end_seconds} />
                          </div>
                        </Field>
                        <Field label={`Speech timing ${segment.speech_rate.toFixed(2)}×`}>
                          <input aria-label="Speech timing rate" className="voice-range" max="2" min="0.5" onChange={(event) => changeDubbingSegment(segment.id, { speech_rate: Number(event.target.value) })} step="0.05" type="range" value={segment.speech_rate} />
                        </Field>
                        <Field label="User-supplied audio segment">
                          <SelectInput onChange={(event) => changeDubbingSegment(segment.id, { audio_asset_id: event.target.value || null, audio_source: event.target.value ? "user_supplied" : null })} value={segment.audio_asset_id ?? ""}>
                            <option value="">No audio attached</option>
                            {audioAssets.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}
                          </SelectInput>
                        </Field>
                      </div>
                      {segment.audio_asset_id ? (
                        <div className="voice-segment-approval">
                          <Button onClick={() => void listenToSegmentAudio(segment.audio_asset_id!)} size="sm">Preview attached audio</Button>
                          <Button
                            onClick={() => changeDubbingSegment(segment.id, { segment_approved: !segment.segment_approved })}
                            size="sm"
                          >
                            {segment.segment_approved ? "Audio approved" : "Approve audio segment"}
                          </Button>
                          <span className="field-hint">
                            {segment.audio_duration_seconds == null
                              ? "Audio duration pending media processing."
                              : `Audio ${segment.audio_duration_seconds.toFixed(2)}s · slot ${(segment.end_seconds - segment.start_seconds).toFixed(2)}s · ${segment.timing_conflict ? "timing conflict: adjust manually" : "fits current slot"}`}
                          </span>
                        </div>
                      ) : (
                        <div className="voice-notice"><LockKeyhole size={15} /><span>No speech generated. Attach user-supplied audio only; regeneration stays unavailable until a tested TTS provider is installed.</span></div>
                      )}
                      <Button
                        disabled={!providers.text_to_speech.available}
                        onClick={() => void regenerateSegment(selectedDubbing.id, segment.id)}
                        size="sm"
                      >
                        {providers.text_to_speech.available ? "Regenerate segment" : "Regeneration unavailable"}
                      </Button>
                    </article>
                  ))}
                </div>
                <div className="voice-plan-actions">
                  <Button disabled={savingDubbing} onClick={() => void saveDubbingPlan()} variant="primary">{savingDubbing ? "Saving…" : "Save dubbing plan"}</Button>
                  <Button onClick={() => void downloadSubtitles(`/voice/dubbing-projects/${selectedDubbing.id}/subtitles/srt`, "dubbing.srt")} size="sm" icon={<Download size={13} />}>Export SRT</Button>
                  <Button onClick={() => void downloadSubtitles(`/voice/dubbing-projects/${selectedDubbing.id}/subtitles/vtt`, "dubbing.vtt")} size="sm" icon={<Download size={13} />}>Export VTT</Button>
                  <Field label="Optional original project video">
                    <SelectInput onChange={(event) => setSelectedDubbingVideoId(event.target.value)} value={selectedDubbingVideoId}>
                      <option value="">Audio file only</option>
                      {videoAssets.filter((asset) => asset.project_id === selectedDubbing.project_id).map((asset) => (
                        <option key={asset.id} value={asset.id}>{asset.name}</option>
                      ))}
                    </SelectInput>
                  </Field>
                  <Button disabled={busy || selectedDubbing.segments_data.some((segment) => !segment.audio_asset_id)} onClick={() => void queueDubbingAudioExport()} size="sm" icon={<FileAudio size={14} />}>
                    {selectedDubbingVideoId ? "Export audio and dubbed MP4" : "Export assembled audio"}
                  </Button>
                </div>
                {segmentAudioUrl ? <audio className="voice-reference-player" controls src={segmentAudioUrl} /> : null}
                <p className="field-hint">Export uses supplied audio only. It preserves complete speech rather than truncating to segment slots; timing conflicts need manual adjustment. Optional video export copies the original video stream without re-encoding.</p>
              </>
            ) : null}
          </Card>
          <ProviderPanel providers={providers} />
        </div>
      ) : null}

      {(current === "Text to speech" || current === "Overview") ? (
        <div className="voice-content-grid">
          <Card className="workspace-main-card">
            <SectionHeading title="Text to speech" description="The interface is ready for an independent synthesis provider adapter." action={<Badge tone="amber">Unavailable</Badge>} />
            <Field label="Script">
              <textarea className="text-area script-area" maxLength={3000} onChange={(event) => setScript(event.target.value)} value={script} />
            </Field>
            <div className="voice-synthesis-controls">
              <Field label="Authorized reference profile">
                <SelectInput aria-label="Authorized voice reference" defaultValue="">
                  <option value="">Select a profile</option>
                  {profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}
                </SelectInput>
              </Field>
              <Field label="Output language">
                <SelectInput defaultValue="en">
                  {LANGUAGES.map(([code, name]) => <option key={code} value={code}>{name}</option>)}
                </SelectInput>
              </Field>
            </div>
            <div className="voice-notice"><LockKeyhole size={15} /><span>No text-to-speech or voice-cloning provider has been selected and tested. No preview audio will be fabricated.</span></div>
            <Button disabled icon={<Sparkles size={14} />} variant="primary">Speech preview unavailable</Button>
          </Card>
          <ProviderPanel providers={providers} />
        </div>
      ) : null}
    </div>
  );
}

function TranscriptSegmentEditor({
  segment,
  saving,
  onSave,
}: {
  segment: VoiceTranscript["segments"][number];
  saving: boolean;
  onSave: (text: string, speaker: string, translation: string) => void;
}) {
  const [text, setText] = useState(segment.text);
  const [speaker, setSpeaker] = useState(segment.speaker_label ?? "");
  const [translation, setTranslation] = useState(segment.translated_text ?? "");
  return (
    <article className="voice-transcript-segment">
      <div className="voice-segment-heading">
        <span className="timestamp">{formatTime(segment.start_seconds)}–{formatTime(segment.end_seconds)}</span>
        <Badge>Timed</Badge>
      </div>
      <Field label="Transcript text">
        <textarea className="text-area" onChange={(event) => setText(event.target.value)} value={text} />
      </Field>
      <div className="voice-transcript-bottom">
        <Field label="Speaker label (manual)">
          <TextInput onChange={(event) => setSpeaker(event.target.value)} value={speaker} />
        </Field>
        <Field label="Translation (manual)">
          <TextInput onChange={(event) => setTranslation(event.target.value)} value={translation} />
        </Field>
        <Button disabled={saving} onClick={() => onSave(text, speaker, translation)} size="sm" icon={<Check size={13} />}>
          {saving ? "Saving…" : "Save"}
        </Button>
      </div>
    </article>
  );
}

function ProviderPanel({ providers }: { providers: VoiceProviders }) {
  return (
    <Card className="workspace-aside-card voice-provider-panel">
      <SectionHeading title="Provider status" description="Providers stay separate and optional." />
      <div className="detail-list">
        <div><span>Transcription</span><strong>{capabilityLabel(providers.transcription)}</strong></div>
        <div><span>Translation</span><strong>{capabilityLabel(providers.translation)}</strong></div>
        <div><span>Speech synthesis</span><strong>{capabilityLabel(providers.text_to_speech)}</strong></div>
        <div><span>Speaker detection</span><strong>{capabilityLabel(providers.speaker_diarization)}</strong></div>
      </div>
      <div className="voice-notice"><ShieldCheck size={15} /><span>Use only recordings you own or have permission to process. Consent records are attestations only.</span></div>
      <div className="voice-licensing-note">
        <Check size={14} />
        <span>MLX Whisper uses a small open-weight model locally. Check model and code licenses before commercial deployment.</span>
      </div>
    </Card>
  );
}
