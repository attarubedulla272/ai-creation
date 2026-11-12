import {
  AudioLines,
  Clapperboard,
  Files,
  FolderKanban,
  LayoutDashboard,
  Scissors,
  Settings2,
  Share2,
  Sparkles,
  WandSparkles,
  type LucideIcon,
} from "lucide-react";

export type NavItem = {
  label: string;
  href: string;
  icon: LucideIcon;
};

export const workspaceLinks: NavItem[] = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { label: "Projects", href: "/projects", icon: FolderKanban },
  { label: "Media library", href: "/media-library", icon: Files },
];

export const studioLinks: NavItem[] = [
  { label: "Voice Studio", href: "/voice-studio", icon: AudioLines },
  { label: "Video Studio", href: "/video-studio", icon: Clapperboard },
  { label: "Content Studio", href: "/content-studio", icon: Sparkles },
  { label: "Smart Clipper", href: "/smart-clipper", icon: Scissors },
  { label: "SEO & Publish", href: "/seo-publish", icon: Share2 },
];

export const resourceLinks: NavItem[] = [
  { label: "Templates", href: "/templates", icon: WandSparkles },
  { label: "Settings", href: "/settings", icon: Settings2 },
];

export const allNavigationLinks = [
  ...workspaceLinks,
  ...studioLinks,
  ...resourceLinks,
];
