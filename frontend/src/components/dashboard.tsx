"use client";

import Link from "next/link";
import {
  ArrowUpRight,
  AudioLines,
  Clapperboard,
  Clock3,
  Film,
  FolderPlus,
  Plus,
  Scissors,
  Share2,
  Sparkles,
  Upload,
  type LucideIcon,
} from "lucide-react";
import { demoProjects } from "@/lib/demo-data";
import { useStudioUI } from "@/components/studio-shell";
import { Badge, Button, Card, SectionHeading } from "@/components/ui";

const modules: {
  title: string;
  description: string;
  href: string;
  icon: LucideIcon;
  accent: string;
  label: string;
}[] = [
  {
    title: "AI Voice Studio",
    description: "Speech, narration, cleanup, and dubbing workspace.",
    href: "/voice-studio",
    icon: AudioLines,
    accent: "violet",
    label: "VOICE",
  },
  {
    title: "AI Video Studio",
    description: "A focused space for timeline editing and finishing.",
    href: "/video-studio",
    icon: Clapperboard,
    accent: "cyan",
    label: "VIDEO",
  },
  {
    title: "Content Studio",
    description: "Shape briefs, scripts, storyboards, and scene plans.",
    href: "/content-studio",
    icon: Sparkles,
    accent: "amber",
    label: "CONTENT",
  },
  {
    title: "Smart Clipper",
    description: "Review short-form ideas from your long-form footage.",
    href: "/smart-clipper",
    icon: Scissors,
    accent: "pink",
    label: "CLIPS",
  },
  {
    title: "SEO & Publish",
    description: "Prepare metadata and organize your release checklist.",
    href: "/seo-publish",
    icon: Share2,
    accent: "green",
    label: "PUBLISH",
  },
];

export function DashboardPage() {
  const { openNewProject, openImportMedia, projects } = useStudioUI();
  const recentProjects = [
    ...projects,
    ...demoProjects,
  ].slice(0, 4);

  return (
    <div className="page-container dashboard-page">
      <div className="welcome-row">
        <div>
          <div className="eyebrow">YOUR CREATIVE WORKSPACE</div>
          <h1>Make room for your next big idea.</h1>
          <p>One calm, considered space for the whole creative process.</p>
        </div>
        <div className="welcome-actions">
          <Button icon={<Upload size={15} />} onClick={openImportMedia}>
            Import media
          </Button>
          <Button
            icon={<Plus size={16} />}
            onClick={openNewProject}
            variant="primary"
          >
            New project
          </Button>
        </div>
      </div>

      <section aria-label="Studio introduction" className="welcome-banner">
        <div className="banner-orb banner-orb-one" />
        <div className="banner-orb banner-orb-two" />
        <div className="banner-copy">
          <Badge tone="violet">YOUR STUDIO, AT A GLANCE</Badge>
          <h2>From the first spark to the final frame.</h2>
          <p>
            Start with a project, organize your media, and find the right
            workspace for what you want to make.
          </p>
          <Link className="banner-link" href="/projects">
            Browse projects <ArrowUpRight size={15} />
          </Link>
        </div>
        <div aria-hidden="true" className="banner-art">
          <span className="banner-art-frame"><Film size={44} /></span>
          <span className="banner-art-wave"><i /><i /><i /><i /><i /><i /><i /></span>
          <span className="banner-art-spark"><Sparkles size={21} /></span>
        </div>
      </section>

      <section className="section-block" id="modules">
        <SectionHeading
          action={<span className="section-caption">5 creative workspaces</span>}
          description="Dedicated spaces for every part of your production."
          eyebrow="THE CREATOR TOOLKIT"
          title="Your creative modules"
        />
        <div className="module-grid">
          {modules.map(({ accent, description, href, icon: Icon, label, title }) => (
            <Link
              aria-label={`Open ${title}. AI features are not implemented.`}
              className={`module-card module-${accent}`}
              href={href}
              key={href}
            >
              <span className="module-card-top">
                <span className="module-icon"><Icon size={20} /></span>
                <Badge>Planned</Badge>
              </span>
              <span className="module-label">{label} WORKSPACE</span>
              <strong>{title}</strong>
              <span className="module-description">{description}</span>
              <span className="module-card-footer">Explore workspace <ArrowUpRight size={14} /></span>
            </Link>
          ))}
        </div>
      </section>

      <section className="section-block dashboard-lower-grid">
        <div className="recent-section">
          <SectionHeading
            action={<Link className="text-link" href="/projects">All projects <ArrowUpRight size={14} /></Link>}
            eyebrow="PICK UP WHERE YOU LEFT OFF"
            title="Recent projects"
          />
          <Card className="recent-project-list">
            {recentProjects.map((project) => (
              <Link className="recent-project-row" href="/projects" key={project.id}>
                <span className={`project-thumbnail thumb-${project.accent}`}>
                  <Film size={18} />
                </span>
                <span className="recent-project-info">
                  <strong>{project.name}</strong>
                  <small>{project.type} <span>·</span> {project.updatedAt}</small>
                </span>
                <Badge tone={project.status === "Local draft" ? "violet" : "neutral"}>
                  {project.status}
                </Badge>
                <ArrowUpRight className="row-arrow" size={15} />
              </Link>
            ))}
            {!projects.length ? (
              <div className="demo-caption"><span /> Sample projects are demonstration data, not generated work.</div>
            ) : null}
          </Card>
        </div>

        <div className="usage-section">
          <SectionHeading eyebrow="WORKSPACE OVERVIEW" title="Usage & storage" />
          <Card className="usage-card">
            <div className="usage-title">
              <span className="usage-icon"><Film size={17} /></span>
              <span><strong>Media storage</strong><small>Illustrative demo values</small></span>
              <Badge>Demo</Badge>
            </div>
            <div className="usage-value">2.4 <span>GB</span><small>of 10 GB</small></div>
            <div aria-label="Demo media storage usage: 24 percent" className="usage-track" role="img">
              <span />
            </div>
            <div className="usage-legend">
              <span><i className="legend-purple" /> Used <strong>24%</strong></span>
              <span><i className="legend-muted" /> Available <strong>76%</strong></span>
            </div>
            <div className="usage-divider" />
            <div className="usage-footnote">
              <Clock3 size={14} />
              <span>Storage tracking is not connected to a backend.</span>
            </div>
          </Card>
        </div>
      </section>

      <footer className="page-footer">
        <span>AI Creator Studio <span>·</span> Foundation milestone</span>
        <span>AI generation is not connected</span>
      </footer>
    </div>
  );
}

export function ProjectsPage() {
  const { projects, openNewProject } = useStudioUI();
  const allProjects = [...projects, ...demoProjects];

  return (
    <div className="page-container">
      <div className="page-heading-row">
        <div>
          <div className="eyebrow">YOUR WORKSPACE</div>
          <h1>Projects</h1>
          <p>Keep your creative work organized in one place.</p>
        </div>
        <Button icon={<FolderPlus size={16} />} onClick={openNewProject} variant="primary">
          New project
        </Button>
      </div>
      <div className="project-summary-row">
        <Card className="project-summary-card">
          <span>All projects</span><strong>{allProjects.length}</strong><small>Includes demonstration samples</small>
        </Card>
        <Card className="project-summary-card">
          <span>Local drafts</span><strong>{projects.length}</strong><small>Saved in this browser</small>
        </Card>
        <Card className="project-summary-card">
          <span>AI jobs</span><strong>—</strong><small>Processing is not available</small>
        </Card>
      </div>
      <section className="section-block">
        <SectionHeading
          action={<Badge>Demo data is labeled</Badge>}
          description="Demo examples are shown alongside drafts you create locally."
          title="All projects"
        />
        <div className="project-grid">
          {allProjects.map((project) => (
            <Card className="project-card" key={project.id}>
              <div className={`project-cover cover-${project.accent}`}>
                <Film size={25} />
                <Badge tone={project.status === "Local draft" ? "violet" : "neutral"}>{project.status}</Badge>
                <span className="cover-lines" aria-hidden="true" />
              </div>
              <div className="project-card-body">
                <div className="project-card-meta"><span>{project.type}</span><span>{project.updatedAt}</span></div>
                <h3>{project.name}</h3>
                <Link className="text-link" href="/content-studio">Open workspace <ArrowUpRight size={14} /></Link>
              </div>
            </Card>
          ))}
        </div>
        <p className="demo-caption"><span /> Sample projects are demonstration data. Local drafts are stored in this browser only.</p>
      </section>
    </div>
  );
}

