"use client";

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { loadMediaPreview } from "@/lib/timeline-api";
import type { MediaAsset } from "@/lib/media-api";
import {
  DEFAULT_TIMELINE_TEXT_STYLE,
  type TimelineClip,
  type TimelineDocument,
  type TimelineTrack,
} from "@/lib/timeline-api";

type Props = {
  baseUrl: string;
  token: string;
  projectId: string;
  timeline: TimelineDocument;
  assets: MediaAsset[];
  playhead: number;
  playing: boolean;
  seekRevision: number;
};

export type TimelinePreviewHandle = {
  resumeAudio: () => Promise<void>;
};

type TimelineEntry = { track: TimelineTrack; clip: TimelineClip; asset?: MediaAsset };
const emptyMediaUrls = new Map<string, string>();

function clipValue(
  clip: TimelineClip,
  property: "x" | "y" | "scale" | "opacity" | "volume",
  time: number,
  fallback: number,
) {
  const keyframes = (clip.keyframes ?? [])
    .filter((keyframe) => keyframe.property === property)
    .sort((left, right) => left.time - right.time);
  if (!keyframes.length || time < keyframes[0]!.time) return fallback;
  const nextIndex = keyframes.findIndex((keyframe) => keyframe.time > time);
  if (nextIndex < 0) return keyframes.at(-1)!.value;
  const left = keyframes[nextIndex - 1]!;
  const right = keyframes[nextIndex]!;
  if (left.interpolation === "hold") return left.value;
  const fraction = (time - left.time) / (right.time - left.time);
  return left.value + (right.value - left.value) * fraction;
}

function activeAt(entry: TimelineEntry, time: number) {
  return time >= entry.clip.start && time < entry.clip.start + entry.clip.duration;
}

export const TimelineCompositePreview = forwardRef<TimelinePreviewHandle, Props>(
  function TimelineCompositePreview({
    baseUrl,
    token,
    projectId,
    timeline,
    assets,
    playhead,
    playing,
    seekRevision,
  }, ref) {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const videoRefs = useRef(new Map<string, HTMLVideoElement>());
    const imageRefs = useRef(new Map<string, HTMLImageElement>());
    const playheadRef = useRef(playhead);
    const audioContextRef = useRef<AudioContext | null>(null);
    const activeSourcesRef = useRef<AudioBufferSourceNode[]>([]);
    const audioBuffersRef = useRef(new Map<string, AudioBuffer>());
    const [loadedMedia, setLoadedMedia] = useState<{ key: string; urls: Map<string, string> } | null>(null);
    const [audioBuffers, setAudioBuffers] = useState<Map<string, AudioBuffer>>(new Map());
    const [scheduledAudioCount, setScheduledAudioCount] = useState(0);
    const [previewError, setPreviewError] = useState("");
    playheadRef.current = playhead;

    const assetsById = useMemo(() => new Map(assets.map((asset) => [asset.id, asset])), [assets]);
    const entries = useMemo(() => timeline.tracks.flatMap((track) =>
      track.clips.map((clip) => ({
        track,
        clip,
        asset: clip.media_asset_id ? assetsById.get(clip.media_asset_id) : undefined,
      }))), [assetsById, timeline.tracks]);
    const mediaIds = useMemo(() => [...new Set(
      entries.flatMap(({ asset }) => asset ? [asset.id] : []),
    )].sort(), [entries]);
    const mediaKey = mediaIds.join(",");
    const urls = loadedMedia?.key === mediaKey ? loadedMedia.urls : emptyMediaUrls;
    const audioEntries = useMemo(() => {
      const soloAudio = timeline.tracks.some((track) => track.type === "audio" && Boolean(track.solo) && !track.muted);
      return entries.filter((entry): entry is TimelineEntry & { asset: MediaAsset } => {
        const { track, asset } = entry;
        if (track.muted || !asset?.metadata_json?.probe?.audio_streams?.length) return false;
        return !soloAudio || (track.type === "audio" && Boolean(track.solo));
      });
    }, [entries, timeline.tracks]);
    const activeVideos = entries.filter(({ track, clip, asset }) =>
      !track.muted && (track.type === "video" || track.type === "overlay")
      && asset?.media_type === "video" && activeAt({ track, clip, asset }, playhead));
    const activeTextCount = entries.filter(({ track, clip }) =>
      !track.muted && (track.type === "overlay" || track.type === "subtitle")
      && Boolean(clip.text) && activeAt({ track, clip }, playhead)).length;
    const hasActiveVisual = entries.some(({ track, clip, asset }) =>
      !track.muted && (track.type === "video" || track.type === "overlay")
      && (asset?.media_type === "video" || asset?.media_type === "image")
      && activeAt({ track, clip, asset }, playhead))
      || activeTextCount > 0;
    const unsupported = useMemo(() => {
      const flags = new Set<string>();
      for (const { track, clip, asset } of entries) {
        if ((track.type === "subtitle" || track.type === "overlay") && clip.text) {
          flags.add("Text typography may differ from the FFmpeg export.");
        }
        if (clip.transition_in?.startsWith("wipe") || clip.transition_out?.startsWith("wipe")) {
          flags.add("Wipe transitions are rendered in the export but not in browser preview.");
        }
        if (asset && asset.media_type !== "video" && asset.media_type !== "image" && track.type !== "audio") {
          flags.add("Some media types cannot be shown in the browser preview.");
        }
      }
      return [...flags];
    }, [entries]);

    useImperativeHandle(ref, () => ({
      async resumeAudio() {
        if (typeof window === "undefined" || !window.AudioContext) {
          throw new Error("Web Audio is not available in this browser.");
        }
        if (!audioContextRef.current || audioContextRef.current.state === "closed") {
          audioContextRef.current = new AudioContext();
        }
        const context = audioContextRef.current;
        await context.resume();
        const missingAudio = [...new Set(audioEntries.map(({ asset }) => asset.id))]
          .filter((assetId) => !audioBuffersRef.current.has(assetId));
        if (!missingAudio.length) return;
        const decoded = await Promise.all(missingAudio.map(async (assetId) => {
          const asset = assetsById.get(assetId);
          const url = urls.get(assetId);
          if (!asset || !url) {
            throw new Error("Timeline audio preview media is still loading.");
          }
          const response = await fetch(url);
          if (!response.ok) throw new Error(`Could not decode audio preview for ${asset.name}.`);
          return [assetId, await context.decodeAudioData(await response.arrayBuffer())] as const;
        }));
        const nextBuffers = new Map(audioBuffersRef.current);
        for (const [assetId, buffer] of decoded) nextBuffers.set(assetId, buffer);
        audioBuffersRef.current = nextBuffers;
        setAudioBuffers(nextBuffers);
      },
    }), [assetsById, audioEntries, urls]);

    useEffect(() => {
      let active = true;
      const urls = new Map<string, string>();
      if (!token || mediaIds.length === 0) {
        setLoadedMedia({ key: mediaKey, urls });
        return () => {};
      }
      void Promise.all(mediaIds.map(async (assetId) => {
        const url = await loadMediaPreview(baseUrl, token, assetId);
        urls.set(assetId, url);
      })).then(() => {
        if (active) setLoadedMedia({ key: mediaKey, urls });
        else urls.forEach((url) => URL.revokeObjectURL(url));
      }).catch((loadError: unknown) => {
        if (active) setPreviewError(loadError instanceof Error ? loadError.message : "Could not load timeline preview media.");
        urls.forEach((url) => URL.revokeObjectURL(url));
      });
      return () => {
        active = false;
        urls.forEach((url) => URL.revokeObjectURL(url));
      };
    }, [baseUrl, mediaIds, mediaKey, projectId, token]);

    useEffect(() => {
      const canvas = canvasRef.current;
      const context = canvas?.getContext("2d");
      if (!canvas || !context) return;
      canvas.width = timeline.width;
      canvas.height = timeline.height;
      const orderedEntries = entries
        .filter(({ track }) => !track.muted && (track.type === "video" || track.type === "overlay" || track.type === "subtitle"))
        .sort((left, right) => timeline.tracks.indexOf(left.track) - timeline.tracks.indexOf(right.track)
          || (left.clip.z_index ?? 0) - (right.clip.z_index ?? 0)
          || left.clip.start - right.clip.start || left.clip.id.localeCompare(right.clip.id));
      let frame = 0;
      const render = () => {
        const currentPlayhead = playheadRef.current;
        context.save();
        context.globalAlpha = 1;
        context.fillStyle = "#000";
        context.fillRect(0, 0, canvas.width, canvas.height);
        for (const entry of orderedEntries) {
          const { track, clip, asset } = entry;
          if (!activeAt(entry, currentPlayhead)) continue;
          if ((track.type === "subtitle" || track.type === "overlay") && clip.text) {
            context.filter = "none";
            const relativeTime = currentPlayhead - clip.start;
            const style = { ...DEFAULT_TIMELINE_TEXT_STYLE, ...clip.text_style };
            const scale = clipValue(clip, "scale", relativeTime, clip.scale ?? 1);
            const positionX = clipValue(clip, "x", relativeTime, clip.position_x ?? 0.5);
            const positionY = clipValue(clip, "y", relativeTime, clip.position_y ?? (track.type === "subtitle" ? 0.88 : 0.5));
            const fontSize = style.font_size;
            const family = style.font_family === "sans-serif" ? "Arial, sans-serif"
              : style.font_family === "serif" ? "Georgia, serif" : "monospace";
            context.font = `${style.font_style} ${style.font_weight} ${fontSize}px ${family}`;
            context.textAlign = "left";
            context.textBaseline = "top";
            const lineHeight = fontSize + Math.max(3, Math.round(fontSize * 0.2));
            const padding = Math.max(4, Math.round(fontSize * 0.2));
            const boxWidth = Math.round(canvas.width * style.width);
            const maxTextWidth = Math.max(fontSize, boxWidth - padding * 2);
            const lines: string[] = [];
            for (const paragraph of clip.text.split(/\r\n?|\n/)) {
              let line = "";
              const words = paragraph.split(/\s+/).filter(Boolean);
              if (!words.length) {
                lines.push("");
                continue;
              }
              for (const word of words) {
                const pieces: string[] = [];
                if (context.measureText(word).width > maxTextWidth) {
                  let piece = "";
                  for (const character of Array.from(word)) {
                    const candidate = `${piece}${character}`;
                    if (piece && context.measureText(candidate).width > maxTextWidth) {
                      pieces.push(piece);
                      piece = character;
                    } else {
                      piece = candidate;
                    }
                  }
                  if (piece) pieces.push(piece);
                } else {
                  pieces.push(word);
                }
                for (const piece of pieces) {
                  const candidate = line ? `${line} ${piece}` : piece;
                  if (line && context.measureText(candidate).width > maxTextWidth) {
                    lines.push(line);
                    line = piece;
                  } else {
                    line = candidate;
                  }
                }
              }
              lines.push(line);
            }
            const boxHeight = Math.max(lines.length * lineHeight + padding * 2, fontSize * 1.5);
            const scaledBoxWidth = boxWidth * scale;
            const scaledBoxHeight = boxHeight * scale;
            const x = (canvas.width - scaledBoxWidth) * positionX;
            const y = (canvas.height - scaledBoxHeight) * positionY;
            const contentWidth = Math.min(maxTextWidth, Math.max(...lines.map((line) => context.measureText(line).width)));
            const backgroundWidth = Math.min(boxWidth, contentWidth + padding * 2);
            const backgroundX = style.alignment === "left" ? 0
              : style.alignment === "right" ? boxWidth - backgroundWidth
                : (boxWidth - backgroundWidth) / 2;
            const contentX = style.alignment === "left" ? backgroundX + padding
              : style.alignment === "right" ? backgroundX + backgroundWidth - padding - contentWidth
                : backgroundX + (backgroundWidth - contentWidth) / 2;
            const verticalOffset = style.vertical_alignment === "top" ? padding
              : style.vertical_alignment === "bottom" ? boxHeight - padding - lines.length * lineHeight
                : (boxHeight - lines.length * lineHeight) / 2;
            const fadeIn = Math.max(
              clip.fade_in ?? 0,
              clip.transition_in === "fade" ? clip.transition_in_duration ?? 0 : 0,
            );
            const fadeOut = Math.max(
              clip.fade_out ?? 0,
              clip.transition_out === "fade" ? clip.transition_out_duration ?? 0 : 0,
            );
            const alpha = Math.min(
              fadeIn > 0 ? relativeTime / fadeIn : 1,
              fadeOut > 0 ? (clip.duration - relativeTime) / fadeOut : 1,
            );
            context.globalAlpha = clipValue(clip, "opacity", relativeTime, clip.opacity ?? 1)
              * Math.max(0, Math.min(1, alpha));
            context.save();
            context.translate(x, y);
            context.scale(scale, scale);
            if (style.background_opacity > 0) {
              context.fillStyle = `${style.background_color}${Math.round(style.background_opacity * 255).toString(16).padStart(2, "0")}`;
              context.fillRect(backgroundX, 0, backgroundWidth, boxHeight);
            }
            context.fillStyle = style.color;
            context.strokeStyle = style.outline_color;
            context.lineWidth = style.outline_width;
            context.shadowColor = style.shadow_blur > 0 ? `${style.shadow_color}dc` : "transparent";
            context.shadowBlur = style.shadow_blur;
            context.shadowOffsetX = style.shadow_blur > 0 ? Math.max(1, Math.floor(style.shadow_blur / 2)) : 0;
            context.shadowOffsetY = context.shadowOffsetX;
            lines.forEach((line, index) => {
              const lineY = verticalOffset + index * lineHeight;
              if (style.outline_width > 0) context.strokeText(line, contentX, lineY, maxTextWidth);
              context.fillText(line, contentX, lineY, maxTextWidth);
            });
            context.restore();
            continue;
          }
          if (!asset || track.type === "subtitle") continue;
          const element = asset.media_type === "video"
            ? videoRefs.current.get(clip.id)
            : asset.media_type === "image" ? imageRefs.current.get(clip.id) : undefined;
          if (!element || (element instanceof HTMLVideoElement
            ? element.readyState < HTMLMediaElement.HAVE_CURRENT_DATA
            : !element.complete || element.naturalWidth === 0)) continue;
          const relativeTime = currentPlayhead - clip.start;
          const scale = clipValue(clip, "scale", relativeTime, clip.scale ?? 1);
          const opacity = clipValue(clip, "opacity", relativeTime, clip.opacity ?? 1);
          const positionX = clipValue(clip, "x", relativeTime, clip.position_x ?? 0.5);
          const positionY = clipValue(clip, "y", relativeTime, clip.position_y ?? 0.5);
          const fadeIn = Math.max(
            clip.fade_in ?? 0,
            clip.transition_in === "fade" ? clip.transition_in_duration ?? 0 : 0,
          );
          const fadeOut = Math.max(
            clip.fade_out ?? 0,
            clip.transition_out === "fade" ? clip.transition_out_duration ?? 0 : 0,
          );
          const fadeFromBlack = fadeIn > 0 ? Math.min(1, relativeTime / fadeIn) : 1;
          const fadeToBlack = fadeOut > 0
            ? Math.min(1, Math.max(0, (clip.duration - relativeTime) / fadeOut))
            : 1;
          const incomingDissolve = clip.transition_in === "cross_dissolve"
            ? Math.min(1, Math.max(0, relativeTime / (clip.transition_in_duration ?? 0.5)))
            : 1;
          const outgoingDissolve = clip.transition_out === "cross_dissolve"
            ? Math.min(1, Math.max(0,
              (clip.duration - relativeTime) / (clip.transition_out_duration ?? 0.5)))
            : 1;
          const filters = [
            `brightness(${100 * (1 + (clip.brightness ?? 0))}%)`,
            `contrast(${100 * (clip.contrast ?? 1)}%)`,
            `saturate(${100 * (clip.saturation ?? 1)}%)`,
            ...((clip.effects ?? []).filter((effect) => effect.enabled).map((effect) => {
              switch (effect.type) {
                case "brightness": return `brightness(${100 * (1 + effect.value)}%)`;
                case "contrast": return `contrast(${100 * effect.value}%)`;
                case "saturation": return `saturate(${100 * effect.value}%)`;
                case "grayscale": return `grayscale(${100 * effect.value}%)`;
                case "blur": return `blur(${effect.value}px)`;
              }
            })),
          ];
          let width = element instanceof HTMLVideoElement ? element.videoWidth : element.naturalWidth;
          let height = element instanceof HTMLVideoElement ? element.videoHeight : element.naturalHeight;
          if (!width || !height) continue;
          const videoTrack = track.type === "video";
          if (videoTrack) {
            const containScale = Math.min(canvas.width / width, canvas.height / height);
            width = Math.round(width * containScale);
            height = Math.round(height * containScale);
          }
          width *= scale;
          height *= scale;
          const x = (canvas.width - width) * positionX;
          const y = (canvas.height - height) * positionY;
          context.filter = `${filters.join(" ")} brightness(${fadeFromBlack * fadeToBlack * 100}%)`;
          context.globalAlpha = Math.max(
            0,
            Math.min(1, opacity * incomingDissolve * outgoingDissolve),
          );
          if (videoTrack) {
            context.fillStyle = "#000";
            context.fillRect(x, y, width, height);
          }
          context.drawImage(element, x, y, width, height);
        }
        context.filter = "none";
        context.globalAlpha = 1;
        context.restore();
        frame = window.requestAnimationFrame(render);
      };
      frame = window.requestAnimationFrame(render);
      return () => window.cancelAnimationFrame(frame);
    }, [entries, timeline.height, timeline.tracks, timeline.width, urls]);

    useEffect(() => {
      const visibleVideos = entries.filter((entry): entry is TimelineEntry & { asset: MediaAsset } =>
        !entry.track.muted && (entry.track.type === "video" || entry.track.type === "overlay")
        && entry.asset?.media_type === "video");
      for (const entry of visibleVideos) {
        const element = videoRefs.current.get(entry.clip.id);
        const url = urls.get(entry.asset.id);
        if (!element || !url) continue;
        if (element.src !== url) {
          element.src = url;
          element.load();
        }
        const isActive = activeAt(entry, playhead);
        const expected = entry.clip.source_start + Math.max(0, playhead - entry.clip.start);
        if (!isActive || !playing) {
          element.pause();
          if (isActive && Math.abs(element.currentTime - expected) > 0.5 / timeline.frame_rate) {
            element.currentTime = expected;
          }
        } else {
          if (Math.abs(element.currentTime - expected) > Math.max(0.15, 2 / timeline.frame_rate)) {
            element.currentTime = expected;
          }
          void element.play().catch(() => setPreviewError("A source video could not play in this browser."));
        }
      }
    }, [entries, playhead, playing, seekRevision, timeline.frame_rate, urls]);

    useEffect(() => {
      const context = audioContextRef.current;
      activeSourcesRef.current.forEach((source) => {
        try { source.stop(); } catch { /* A scheduled node may already have ended. */ }
        source.disconnect();
      });
      activeSourcesRef.current = [];
      setScheduledAudioCount(0);
      if (!playing || !context || context.state !== "running") return;
      const currentPlayhead = playheadRef.current;
      const now = context.currentTime;
      let scheduledCount = 0;
      for (const entry of audioEntries) {
        const { track, clip, asset } = entry;
        if (!asset) continue;
        const buffer = audioBuffers.get(asset.id);
        if (!buffer || clip.start + clip.duration <= currentPlayhead) continue;
        const offset = Math.max(0, currentPlayhead - clip.start);
        const startAt = now + Math.max(0, clip.start - currentPlayhead);
        const remaining = clip.duration - offset;
        const source = context.createBufferSource();
        const gain = context.createGain();
        source.buffer = buffer;
        source.connect(gain);
        gain.connect(context.destination);
        const trackVolume = Math.max(0, track.volume ?? 1);
        const clipVolume = (time: number) => Math.max(0,
          clipValue(clip, "volume", time, clip.volume ?? 1) * trackVolume);
        const fadeIn = Math.max(clip.fade_in ?? 0, clip.transition_in && clip.transition_in !== "none"
          ? clip.transition_in_duration ?? 0 : 0);
        const fadeOut = Math.max(clip.fade_out ?? 0, clip.transition_out && clip.transition_out !== "none"
          ? clip.transition_out_duration ?? 0 : 0);
        const factor = (time: number) => {
          const incoming = fadeIn > 0 ? Math.min(1, Math.max(0, time / fadeIn)) : 1;
          const outgoing = fadeOut > 0 ? Math.min(1, Math.max(0, (clip.duration - time) / fadeOut)) : 1;
          return incoming * outgoing;
        };
        const currentVolume = clipVolume(offset) * factor(offset);
        gain.gain.setValueAtTime(currentVolume, startAt);
        const points = new Set<number>([clip.duration]);
        for (const keyframe of clip.keyframes ?? []) {
          if (keyframe.property === "volume" && keyframe.time > offset) points.add(keyframe.time);
        }
        if (fadeIn > offset) points.add(fadeIn);
        if (fadeOut > 0 && clip.duration - fadeOut > offset) points.add(clip.duration - fadeOut);
        for (const point of [...points].sort((a, b) => a - b)) {
          const when = startAt + point - offset;
          gain.gain.linearRampToValueAtTime(clipVolume(point) * factor(point), when);
        }
        source.start(startAt, clip.source_start + offset, remaining);
        activeSourcesRef.current.push(source);
        scheduledCount += 1;
      }
      setScheduledAudioCount(scheduledCount);
      return () => {
        activeSourcesRef.current.forEach((source) => {
          try { source.stop(); } catch { /* A scheduled node may already have ended. */ }
          source.disconnect();
        });
        activeSourcesRef.current = [];
        setScheduledAudioCount(0);
      };
    }, [audioBuffers, audioEntries, playing, seekRevision, timeline]);

    useEffect(() => {
      const onVisibilityChange = () => {
        if (document.visibilityState === "hidden") {
          videoRefs.current.forEach((video) => video.pause());
          activeSourcesRef.current.forEach((source) => {
            try { source.stop(); } catch { /* A scheduled node may already have ended. */ }
          });
          activeSourcesRef.current = [];
        }
      };
      document.addEventListener("visibilitychange", onVisibilityChange);
      return () => document.removeEventListener("visibilitychange", onVisibilityChange);
    }, []);

    useEffect(() => () => {
      activeSourcesRef.current.forEach((source) => {
        try { source.stop(); } catch { /* A scheduled node may already have ended. */ }
        source.disconnect();
      });
      void audioContextRef.current?.close();
    }, []);

    const audioActive = audioEntries.filter((entry) => activeAt(entry, playhead)).length;
    return (
      <div className="timeline-composite-preview" data-testid="timeline-composite-preview">
        <canvas
          aria-label="Composite timeline preview"
          data-active-audio-count={audioActive}
          data-active-text-count={activeTextCount}
          data-active-video-count={activeVideos.length}
          data-decoded-audio-count={audioBuffers.size}
          data-audio-context-state={audioContextRef.current?.state ?? "unavailable"}
          data-scheduled-audio-count={scheduledAudioCount}
          data-has-active-visual={hasActiveVisual}
          data-playhead={playhead.toFixed(3)}
          data-testid="composite-preview-canvas"
          ref={canvasRef}
        />
        <div className="editor-preview-decoders" aria-hidden="true">
          {entries.filter(({ asset }) => asset?.media_type === "video").map(({ clip, asset }) => (
            <video
              key={clip.id}
              data-preview-asset={asset?.id}
              muted
              playsInline
              preload="auto"
              ref={(element) => {
                if (element) videoRefs.current.set(clip.id, element);
                else videoRefs.current.delete(clip.id);
              }}
            />
          ))}
          {entries.filter(({ asset }) => asset?.media_type === "image").map(({ clip, asset }) => (
            // eslint-disable-next-line @next/next/no-img-element -- Native decoding feeds canvas composition.
            <img
              key={clip.id}
              alt=""
              data-preview-asset={asset?.id}
              ref={(element) => {
                if (element) imageRefs.current.set(clip.id, element);
                else imageRefs.current.delete(clip.id);
                const url = asset ? urls.get(asset.id) : undefined;
                if (element && url && element.src !== url) element.src = url;
              }}
            />
          ))}
        </div>
        {!hasActiveVisual
          && <div className="editor-preview-placeholder" data-testid="preview-gap-message">No visible video at this playhead position</div>}
        <span className="visually-hidden" data-testid="preview-active-audio-count">{audioActive}</span>
        {unsupported.length > 0 && (
          <div className="editor-preview-notice" role="status" data-testid="preview-limitations">
            {unsupported.join(" ")}
          </div>
        )}
        {previewError && <p className="editor-error" role="alert">{previewError}</p>}
      </div>
    );
  },
);
