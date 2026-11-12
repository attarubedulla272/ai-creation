import {
  AudioLines,
  Clapperboard,
  Scissors,
  Share2,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

export type DemoProject = {
  id: string;
  name: string;
  type: string;
  updatedAt: string;
  status: "Demo" | "Local draft";
  accent: string;
};

export type ModuleDefinition = {
  title: string;
  eyebrow: string;
  description: string;
  icon: LucideIcon;
  accent: string;
  nav: string[];
  demoStatus: string;
};

export const demoProjects: DemoProject[] = [
  {
    id: "p1",
    name: "The quiet art of starting over",
    type: "Documentary · 16:9",
    updatedAt: "Edited 2 hours ago",
    status: "Demo",
    accent: "lavender",
  },
  {
    id: "p2",
    name: "Small rituals, big mornings",
    type: "Short-form · 9:16",
    updatedAt: "Edited yesterday",
    status: "Demo",
    accent: "blue",
  },
  {
    id: "p3",
    name: "A field guide to slow travel",
    type: "Travel story · 16:9",
    updatedAt: "Edited 3 days ago",
    status: "Demo",
    accent: "coral",
  },
];

export const modules: Record<string, ModuleDefinition> = {
  "voice-studio": {
    title: "Voice Studio",
    eyebrow: "AUDIO WORKSPACE",
    description:
      "Prepare voice, transcription, and dubbing projects in one focused workspace.",
    icon: AudioLines,
    accent: "violet",
    nav: ["Overview", "Text to speech", "Transcription", "Dubbing", "Voice library"],
    demoStatus: "Voice generation and cloning are not implemented",
  },
  "video-studio": {
    title: "Video Studio",
    eyebrow: "EDITING WORKSPACE",
    description:
      "Arrange multi-track media, transitions, overlays, subtitles, and local FFmpeg exports.",
    icon: Clapperboard,
    accent: "cyan",
    nav: ["Editor", "Timeline", "Captions", "Color", "Export"],
    demoStatus: "Local timeline rendering · AI video generation not included",
  },
  "content-studio": {
    title: "Content Studio",
    eyebrow: "IDEA TO STORYBOARD",
    description:
      "Turn a creative brief into a structured script and scene-by-scene plan.",
    icon: Sparkles,
    accent: "amber",
    nav: ["Brief", "Script", "Storyboard", "Character Bible", "Environments", "Style Guide", "Continuity", "Model Registry"],
    demoStatus: "AI writing and real video generation are not implemented",
  },
  "smart-clipper": {
    title: "Smart Clipper",
    eyebrow: "LONG-FORM TO SHORTS",
    description:
      "Review candidate moments and prepare a short-form editing plan.",
    icon: Scissors,
    accent: "pink",
    nav: ["Overview", "Highlights", "Clip editor", "Captions", "Batch export"],
    demoStatus: "Local analysis and clip export workspace",
  },
  "seo-publish": {
    title: "SEO & Publish",
    eyebrow: "PREPARE YOUR RELEASE",
    description:
      "Prepare persistent metadata, local thumbnails, and a release calendar.",
    icon: Share2,
    accent: "green",
    nav: ["Overview", "Metadata", "Thumbnail", "Schedule", "YouTube", "Analytics"],
    demoStatus: "Official YouTube integration requires operator-configured Google credentials",
  },
};

export const demoMedia = [
  { name: "Morning light — opening shot", type: "Video", size: "128 MB", duration: "00:24" },
  { name: "Field recording — birdsong", type: "Audio", size: "18 MB", duration: "01:12" },
  { name: "Moodboard — soft horizons", type: "Image", size: "4.2 MB", duration: "—" },
  { name: "Interview — take 02", type: "Video", size: "342 MB", duration: "08:36" },
];

export const demoTemplates = [
  { title: "Creator introduction", type: "Short-form", duration: "30–45 sec", color: "lavender" },
  { title: "Mini documentary", type: "Storytelling", duration: "3–5 min", color: "blue" },
  { title: "Product story", type: "Brand film", duration: "60–90 sec", color: "coral" },
  { title: "Podcast highlights", type: "Clips", duration: "15–60 sec", color: "mint" },
];
