"use client";

import { useState } from "react";
import {
  ArrowDownToLine,
  AudioLines,
  Clapperboard,
  Download,
  FileVideo2,
  Layers3,
  Play,
  Plus,
  Scissors,
  Settings2,
  Sparkles,
} from "lucide-react";
import { modules } from "@/lib/demo-data";
import { Badge, Button, Card, Field, SectionHeading, SelectInput } from "@/components/ui";
import { VideoEditor } from "@/components/video-editor";
import { VoiceStudioWorkspace } from "@/components/voice-studio-workspace";
import { ContentStudioWorkspace } from "@/components/content-studio-workspace";
import { SmartClipperWorkspace } from "@/components/smart-clipper-workspace";
import { SeoPublishWorkspace } from "@/components/seo-publish-workspace";

type ModuleSlug = keyof typeof modules;

function WorkspaceTabs({
  items,
  current,
  onChange,
}: {
  items: string[];
  current: string;
  onChange: (item: string) => void;
}) {
  return (
    <div
      aria-label="Workspace sections"
      className="workspace-tabs"
      onKeyDown={(event) => {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        const tabs = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
        const index = tabs.indexOf(document.activeElement as HTMLButtonElement);
        const offset = event.key === "ArrowRight" ? 1 : -1;
        const nextIndex = (index + offset + tabs.length) % tabs.length;
        event.preventDefault();
        tabs[nextIndex]?.focus();
        if (items[nextIndex]) onChange(items[nextIndex]);
      }}
      role="tablist"
    >
      {items.map((item) => (
        <button
          aria-selected={current === item}
          className={current === item ? "workspace-tab workspace-tab-active" : "workspace-tab"}
          key={item}
          onClick={() => onChange(item)}
          role="tab"
          type="button"
        >
          {item}
        </button>
      ))}
    </div>
  );
}

function WorkspaceHeader({
  slug,
  onChange,
  current,
}: {
  slug: ModuleSlug;
  onChange: (item: string) => void;
  current: string;
}) {
  const definition = modules[slug];
  const Icon = definition.icon;

  return (
    <>
      <div className="module-page-heading">
        <div className="module-heading-title">
          <span className={`module-heading-icon accent-${definition.accent}`}><Icon size={20} /></span>
          <div>
            <div className="eyebrow">{definition.eyebrow}</div>
            <h1>{definition.title}</h1>
          </div>
        </div>
        <Badge>{definition.demoStatus}</Badge>
      </div>
      <div className="module-heading-description">
        <p>{definition.description}</p>
        <Badge>
          {slug === "video-studio"
            ? "Local editing workspace"
            : slug === "voice-studio"
              ? "Consent-aware workspace"
                : slug === "content-studio"
                  ? "Persistent project planning"
                    : slug === "smart-clipper"
                      ? "Local analysis and FFmpeg exports"
                      : slug === "seo-publish"
                        ? "Persistent release preparation"
                        : "Demonstration workspace"}
        </Badge>
      </div>
      <WorkspaceTabs current={current} items={definition.nav} onChange={onChange} />
    </>
  );
}

function VoiceWorkspace({ current }: { current: string }) {
  return <VoiceStudioWorkspace current={current} />;
}

const timelineClips = [
  { label: "Opening shot · demo footage", width: "43%", tone: "timeline-clip-purple" },
  { label: "Morning light · sample", width: "31%", tone: "timeline-clip-blue" },
  { label: "Interview take · demo", width: "57%", tone: "timeline-clip-teal" },
];

function VideoWorkspace({ current }: { current: string }) {
  if (current === "Timeline" || current === "Editor") {
    return (
      <div className="video-editor">
        <Card className="editor-preview-card">
          <div className="editor-toolbar">
            <div className="editor-tool-group"><Button disabled size="sm"><Scissors size={14} /> Split</Button><Button disabled icon={<Layers3 size={14} />} size="sm">Layer</Button></div>
            <Badge>Preview only · demo</Badge>
            <Button disabled icon={<ArrowDownToLine size={14} />} size="sm">Export unavailable</Button>
          </div>
          <div className="video-preview">
            <span className="preview-frame-icon"><Clapperboard size={28} /></span>
            <span className="preview-watermark">DEMO FRAME · NO VIDEO LOADED</span>
            <span className="preview-ratio">16:9</span>
          </div>
          <div className="preview-transport">
            <Button aria-label="Play preview" disabled icon={<Play size={15} />} size="sm" />
            <span>00:00:00:00</span><span className="transport-divider">/</span><span>00:00:32:00</span>
            <span className="transport-spacer" /><Button disabled icon={<Settings2 size={15} />} size="sm">Preview settings</Button>
          </div>
        </Card>
        <Card className="timeline-card">
          <div className="timeline-heading"><span><strong>Timeline</strong><small>Sample arrangement · no playable media</small></span><Button disabled icon={<Plus size={14} />} size="sm">Add track</Button></div>
          <div aria-label="Demonstration video timeline" className="timeline-grid">
            <div className="timeline-ruler"><span>00:00</span><span>00:08</span><span>00:16</span><span>00:24</span><span>00:32</span></div>
            {timelineClips.map((clip, index) => (
              <div className="timeline-row" key={clip.label}>
                <span className="timeline-track-name">{index === 2 ? <AudioLines size={13} /> : <FileVideo2 size={13} />} {index === 2 ? "A1" : `V${index + 1}`}</span>
                <div className="timeline-track">
                  <span className={`timeline-clip ${clip.tone}`} style={{ width: clip.width }}>{clip.label}</span>
                </div>
              </div>
            ))}
          </div>
          <div className="notice-strip"><Clapperboard size={15} /><span>Timeline tracks are illustrative. Trimming, playback, effects, and export are not implemented.</span></div>
        </Card>
      </div>
    );
  }

  if (current === "Captions") {
    return (
      <div className="workspace-columns">
        <Card className="workspace-main-card"><SectionHeading title="Caption editor" description="Sample subtitle cues for layout preview." /><div className="caption-line"><span>00:00:01.200 → 00:00:04.100</span><strong>We often think a fresh start has to be loud.</strong><Badge>Sample</Badge></div><div className="caption-line"><span>00:00:04.400 → 00:00:09.800</span><strong>But sometimes it begins quietly.</strong><Badge>Sample</Badge></div><Button disabled>Subtitle editing unavailable</Button></Card>
        <Card className="workspace-aside-card"><SectionHeading title="Caption style" /><Field label="Typeface"><SelectInput defaultValue="Studio Sans"><option>Studio Sans</option><option>Serif</option></SelectInput></Field><Field label="Position"><SelectInput defaultValue="Lower third"><option>Lower third</option><option>Center</option></SelectInput></Field></Card>
      </div>
    );
  }

  if (current === "Color") {
    return <Card className="workspace-main-card"><SectionHeading title="Color finishing" description="Color controls are shown as a layout preview only." /><div className="color-control-grid">{["Exposure", "Contrast", "Saturation", "Temperature"].map((label) => <Field key={label} label={label}><input aria-label={label} className="range-input" disabled max="100" min="0" type="range" value="50" readOnly /></Field>)}</div><div className="notice-strip"><Settings2 size={15} /><span>Color grading is not applied to any footage.</span></div></Card>;
  }

  return <Card className="workspace-main-card"><SectionHeading title="Export settings" description="Set expectations before an export workflow is available." /><div className="export-options"><Field label="Resolution"><SelectInput defaultValue="1920 × 1080 (Demo)"><option>1920 × 1080 (Demo)</option><option>1080 × 1920 (Demo)</option></SelectInput></Field><Field label="Frame rate"><SelectInput defaultValue="24 fps (Demo)"><option>24 fps (Demo)</option><option>30 fps (Demo)</option></SelectInput></Field><Field label="Format"><SelectInput defaultValue="MP4 (Demo)"><option>MP4 (Demo)</option><option>MOV (Demo)</option></SelectInput></Field></div><Button disabled icon={<Download size={15} />} variant="primary">Export is not implemented</Button></Card>;
}

function ContentWorkspace({ current }: { current: string }) {
  return <ContentStudioWorkspace current={current} />;
}

function ClipperWorkspace({ current }: { current: string }) {
  return <SmartClipperWorkspace current={current} />;
}

function SeoWorkspace({ current }: { current: string }) {
  return <SeoPublishWorkspace current={current} />;
}

export function ModuleWorkspace({ slug }: { slug: ModuleSlug }) {
  const definition = modules[slug];
  const [current, setCurrent] = useState(definition.nav[0]);
  return (
    <div className={`page-container module-page module-${slug}`}>
      <WorkspaceHeader current={current} onChange={setCurrent} slug={slug} />
      {slug === "voice-studio" ? <VoiceWorkspace current={current} /> : null}
      {slug === "video-studio" && (current === "Editor" || current === "Timeline")
        ? <VideoEditor />
        : slug === "video-studio" ? <VideoWorkspace current={current} /> : null}
      {slug === "content-studio" ? <ContentWorkspace current={current} /> : null}
      {slug === "smart-clipper" ? <ClipperWorkspace current={current} /> : null}
      {slug === "seo-publish" ? <SeoWorkspace current={current} /> : null}
      {slug !== "voice-studio" && slug !== "content-studio" && slug !== "smart-clipper" && !(slug === "video-studio" && (current === "Editor" || current === "Timeline")) && (
        <div className="module-footer-note"><Sparkles size={14} /><span>{definition.demoStatus}. {slug === "seo-publish" ? "Saved release data belongs to the authenticated user; planned dates do not publish externally." : "All visible assets and metadata are sample content unless clearly marked as a local draft."}</span></div>
      )}
    </div>
  );
}
