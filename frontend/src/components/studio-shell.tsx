"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Bell,
  ChevronDown,
  Command,
  Film,
  LogOut,
  Menu,
  Plus,
  Search,
  Settings2,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  allNavigationLinks,
  resourceLinks,
  studioLinks,
  workspaceLinks,
  type NavItem,
} from "@/lib/navigation";
import type { DemoProject } from "@/lib/demo-data";
import { Badge, Button, Dialog, Field, SelectInput, TextInput } from "@/components/ui";

type DemoMediaAsset = {
  id: string;
  name: string;
  type: string;
  size: number;
  addedAt: string;
};

type StudioUIContextValue = {
  projects: DemoProject[];
  media: DemoMediaAsset[];
  openNewProject: () => void;
  openImportMedia: () => void;
  saveDemoProject: (name: string, type: string) => void;
  saveDemoMedia: (files: File[]) => void;
  removeDemoMedia: (id: string) => void;
  notify: (message: string, tone?: "success" | "error") => void;
};

const StudioUIContext = createContext<StudioUIContextValue | null>(null);

const PROJECTS_KEY = "ai-creator-studio:demo-projects";
const MEDIA_KEY = "ai-creator-studio:demo-media";

export function useStudioUI() {
  const context = useContext(StudioUIContext);
  if (!context) throw new Error("useStudioUI must be used inside StudioShell.");
  return context;
}

function readStorage<T>(key: string, fallback: T): T {
  try {
    const stored = window.localStorage.getItem(key);
    return stored ? (JSON.parse(stored) as T) : fallback;
  } catch {
    return fallback;
  }
}

function NavGroup({
  heading,
  items,
  pathname,
  onNavigate,
}: {
  heading: string;
  items: NavItem[];
  pathname: string;
  onNavigate: () => void;
}) {
  return (
    <div className="nav-group">
      <div className="nav-heading">{heading}</div>
      {items.map(({ href, icon: Icon, label }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            aria-current={active ? "page" : undefined}
            className={`nav-link${active ? " nav-link-active" : ""}`}
            href={href}
            key={href}
            onClick={onNavigate}
          >
            <Icon size={17} strokeWidth={1.8} />
            <span>{label}</span>
          </Link>
        );
      })}
    </div>
  );
}

function Sidebar({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  const pathname = usePathname();

  return (
    <>
      {isOpen ? (
        <button
          aria-label="Close navigation"
          className="mobile-nav-backdrop"
          onClick={onClose}
          type="button"
        />
      ) : null}
      <aside className={`sidebar${isOpen ? " sidebar-open" : ""}`}>
        <div className="sidebar-brand-row">
          <Link aria-label="AI Creator Studio dashboard" className="brand" href="/dashboard">
            <span aria-hidden="true" className="brand-mark">
              <Sparkles size={18} />
            </span>
            <span className="brand-name">
              AI Creator
              <span>STUDIO</span>
            </span>
          </Link>
          <button
            aria-label="Close navigation"
            className="icon-button mobile-nav-close"
            onClick={onClose}
            type="button"
          >
            <X size={18} />
          </button>
        </div>

        <button className="workspace-switcher" type="button" aria-label="Personal workspace">
          <span aria-hidden="true" className="workspace-avatar">A</span>
          <span className="workspace-label">
            <strong>Personal workspace</strong>
            <span>Free workspace</span>
          </span>
          <ChevronDown aria-hidden="true" className="workspace-caret" size={15} />
        </button>

        <nav aria-label="Main navigation" className="side-nav">
          <NavGroup
            heading="WORKSPACE"
            items={workspaceLinks}
            onNavigate={onClose}
            pathname={pathname}
          />
          <NavGroup
            heading="CREATE"
            items={studioLinks}
            onNavigate={onClose}
            pathname={pathname}
          />
          <NavGroup
            heading="PREFERENCES"
            items={resourceLinks}
            onNavigate={onClose}
            pathname={pathname}
          />
        </nav>

        <div className="sidebar-bottom">
          <div className="storage-card">
            <div className="storage-card-heading">
              <span>Workspace storage</span>
              <Badge tone="violet">Demo</Badge>
            </div>
            <div className="storage-amount">2.4 GB <span>of 10 GB</span></div>
            <div
              aria-label="Demo storage usage: 24 percent"
              className="storage-track"
              role="img"
            >
              <span />
            </div>
            <p>Illustrative usage only · local storage not connected</p>
          </div>
          <div className="sidebar-user">
            <span aria-hidden="true" className="profile-avatar">A</span>
            <span>
              <strong>Alex Morgan</strong>
              <small>Demo account</small>
            </span>
          </div>
        </div>
      </aside>
    </>
  );
}

function Topbar({
  onOpenNewProject,
  onToggleNav,
}: {
  onOpenNewProject: () => void;
  onToggleNav: () => void;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const searchRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [activeSearchIndex, setActiveSearchIndex] = useState(0);
  const [menu, setMenu] = useState<"notifications" | "profile" | null>(null);
  const currentPage = allNavigationLinks.find(({ href }) => href === pathname);
  const filteredLinks = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return normalized
      ? allNavigationLinks.filter(({ label }) => label.toLowerCase().includes(normalized))
      : allNavigationLinks.slice(0, 5);
  }, [query]);

  useEffect(() => {
    function handleShortcut(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchRef.current?.focus();
        setSearchOpen(true);
      }
      if (event.key === "Escape") {
        setSearchOpen(false);
        setMenu(null);
      }
    }

    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, []);

  function navigateToFirstResult(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (filteredLinks[activeSearchIndex]) {
      router.push(filteredLinks[activeSearchIndex].href);
      setQuery("");
      setSearchOpen(false);
      searchRef.current?.blur();
    }
  }

  return (
    <header className="topbar">
      <div className="topbar-left">
        <button
          aria-label="Open navigation"
          className="icon-button mobile-menu-button"
          onClick={onToggleNav}
          type="button"
        >
          <Menu size={19} />
        </button>
        <div aria-label={`Current page: ${currentPage?.label ?? "Studio"}`} className="breadcrumbs">
          <span>Workspace</span>
          <span aria-hidden="true" className="breadcrumb-divider">/</span>
          <strong>{currentPage?.label ?? "Studio"}</strong>
        </div>
      </div>
      <div className="topbar-actions">
        <div className="top-search">
          <form onSubmit={navigateToFirstResult}>
            <Search aria-hidden="true" size={15} />
            <input
              aria-label="Search workspace"
              aria-expanded={searchOpen}
              aria-controls="search-results"
              aria-haspopup="listbox"
              aria-autocomplete="list"
              autoComplete="off"
              onBlur={() => window.setTimeout(() => setSearchOpen(false), 120)}
              onChange={(event) => {
                setQuery(event.target.value);
                setSearchOpen(true);
                setActiveSearchIndex(0);
              }}
              onKeyDown={(event) => {
                if (event.key === "ArrowDown" && filteredLinks.length) {
                  event.preventDefault();
                  setSearchOpen(true);
                  setActiveSearchIndex((index) => (index + 1) % filteredLinks.length);
                } else if (event.key === "ArrowUp" && filteredLinks.length) {
                  event.preventDefault();
                  setSearchOpen(true);
                  setActiveSearchIndex((index) => (index - 1 + filteredLinks.length) % filteredLinks.length);
                }
              }}
              onFocus={() => setSearchOpen(true)}
              placeholder="Search anything..."
              ref={searchRef}
              aria-activedescendant={
                searchOpen && filteredLinks[activeSearchIndex]
                  ? `search-result-${filteredLinks[activeSearchIndex].href.slice(1).replaceAll("/", "-")}`
                  : undefined
              }
              role="combobox"
              type="search"
              value={query}
            />
            <kbd><Command size={10} /> K</kbd>
          </form>
          {searchOpen ? (
            <div className="search-results" id="search-results" aria-label="Navigation results" role="listbox">
              <div className="search-results-heading">
                {query ? "Matching pages" : "Quick navigation"}
              </div>
              {filteredLinks.length ? filteredLinks.map(({ href, icon: Icon, label }, index) => (
                <Link
                  aria-selected={index === activeSearchIndex}
                  className={`search-result${index === activeSearchIndex ? " search-result-active" : ""}`}
                  href={href}
                  id={`search-result-${href.slice(1).replaceAll("/", "-")}`}
                  key={href}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => {
                    setSearchOpen(false);
                    setQuery("");
                  }}
                  role="option"
                >
                  <Icon size={15} />
                  <span>{label}</span>
                  <span aria-hidden="true">↵</span>
                </Link>
              )) : <p className="search-empty">No workspace pages match “{query}”.</p>}
              <div className="search-hint">Press Enter to open the first result · ⌘K to search</div>
            </div>
          ) : null}
        </div>
        <div className="topbar-menu-wrap">
          <button
            aria-expanded={menu === "notifications"}
            aria-label="Notifications"
            className="icon-button notification-button"
            onClick={() => setMenu(menu === "notifications" ? null : "notifications")}
            type="button"
          >
            <Bell size={17} />
            <span className="notification-dot" />
          </button>
          {menu === "notifications" ? (
            <div className="topbar-popover notification-popover">
              <div className="popover-title">Notifications <Badge>Demo</Badge></div>
              <div className="notification-item">
                <span className="notification-indicator" />
                <span><strong>Welcome to your studio</strong><small>Explore your workspace foundation.</small></span>
              </div>
              <div className="notification-item">
                <span className="notification-indicator muted" />
                <span><strong>Modules are in planning</strong><small>AI workflows are not connected.</small></span>
              </div>
            </div>
          ) : null}
        </div>
        <div className="topbar-menu-wrap">
          <button
            aria-expanded={menu === "profile"}
            aria-label="Open account menu"
            className="profile-trigger"
            onClick={() => setMenu(menu === "profile" ? null : "profile")}
            type="button"
          >
            <span aria-hidden="true" className="profile-avatar">A</span>
            <ChevronDown size={13} />
          </button>
          {menu === "profile" ? (
            <div className="topbar-popover profile-popover">
              <div className="profile-menu-summary">
                <span className="profile-avatar">A</span>
                <span><strong>Alex Morgan</strong><small>Demo account</small></span>
              </div>
              <Link href="/settings" onClick={() => setMenu(null)}><Settings2 size={15} /> Settings</Link>
              <button onClick={() => setMenu(null)} type="button"><LogOut size={15} /> Demo workspace</button>
            </div>
          ) : null}
        </div>
        <Button
          className="topbar-new-project"
          icon={<Plus size={15} />}
          onClick={onOpenNewProject}
          size="sm"
          variant="primary"
        >
          New project
        </Button>
      </div>
    </header>
  );
}

function NewProjectDialog({
  onClose,
  onSave,
}: {
  onClose: () => void;
  onSave: (name: string, type: string) => void;
}) {
  const [name, setName] = useState("");
  const [type, setType] = useState("Video project");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleanName = name.trim();
    if (!cleanName) return;
    onSave(cleanName, type);
    onClose();
  }

  return (
    <Dialog
      description="This creates a project draft in this browser only. It is not synced to a server."
      onClose={onClose}
      title="Create a project"
    >
      <form className="dialog-form" onSubmit={handleSubmit}>
        <Field label="Project name">
          <TextInput
            autoFocus
            maxLength={80}
            onChange={(event) => setName(event.target.value)}
            placeholder="e.g. A story about slow mornings"
            required
            value={name}
          />
        </Field>
        <Field label="Project type">
          <SelectInput onChange={(event) => setType(event.target.value)} value={type}>
            <option>Video project</option>
            <option>Audio project</option>
            <option>Content plan</option>
            <option>Short-form clips</option>
          </SelectInput>
        </Field>
        <div className="dialog-note">
          <Sparkles size={15} />
          <span>AI generation is not connected. This creates a local demo draft.</span>
        </div>
        <div className="dialog-actions">
          <Button onClick={onClose}>Cancel</Button>
          <Button disabled={!name.trim()} type="submit" variant="primary">Create local draft</Button>
        </div>
      </form>
    </Dialog>
  );
}

function ImportMediaDialog({
  onClose,
  onSave,
}: {
  onClose: () => void;
  onSave: (files: File[]) => void;
}) {
  const [files, setFiles] = useState<File[]>([]);

  return (
    <Dialog
      className="import-dialog"
      description="Media files are not uploaded or copied. Only file names and sizes are saved in this browser demo."
      onClose={onClose}
      title="Import media"
    >
      <div className="dialog-form">
        <label className="dropzone">
          <input
            accept="audio/*,video/*,image/*"
            multiple
            onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
            type="file"
          />
          <span className="dropzone-icon"><Upload size={19} /></span>
          <strong>Select media files</strong>
          <span>Audio, video, and images · local selection only</span>
        </label>
        {files.length ? (
          <div className="selected-files" aria-live="polite">
            {files.map((file) => (
              <div className="selected-file" key={`${file.name}-${file.size}`}>
                <Film size={14} />
                <span>{file.name}</span>
                <small>{(file.size / (1024 * 1024)).toFixed(1)} MB</small>
              </div>
            ))}
          </div>
        ) : null}
        <div className="dialog-note">
          <Upload size={15} />
          <span>Files stay on your device. This demo stores metadata only; no upload or processing occurs.</span>
        </div>
        <div className="dialog-actions">
          <Button onClick={onClose}>Cancel</Button>
          <Button
            disabled={!files.length}
            onClick={() => {
              onSave(files);
              onClose();
            }}
            variant="primary"
          >
            Add to demo library
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

export function StudioShell({ children }: { children: ReactNode }) {
  const [projects, setProjects] = useState<DemoProject[]>([]);
  const [media, setMedia] = useState<DemoMediaAsset[]>([]);
  const [dialog, setDialog] = useState<"project" | "media" | null>(null);
  const [notice, setNotice] = useState<{ message: string; tone: "success" | "error" } | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setProjects(readStorage<DemoProject[]>(PROJECTS_KEY, []));
      setMedia(readStorage<DemoMediaAsset[]>(MEDIA_KEY, []));
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 4200);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const notify = useCallback((message: string, tone: "success" | "error" = "success") => {
    setNotice({ message, tone });
  }, []);

  const saveDemoProject = useCallback((name: string, type: string) => {
    const project: DemoProject = {
      id: crypto.randomUUID(),
      name,
      type,
      updatedAt: "Created just now",
      status: "Local draft",
      accent: "lavender",
    };
    try {
      const next = [project, ...readStorage<DemoProject[]>(PROJECTS_KEY, [])];
      window.localStorage.setItem(PROJECTS_KEY, JSON.stringify(next));
      setProjects(next);
      notify("Local demo draft created in this browser.");
    } catch {
      notify("Could not save this draft in browser storage.", "error");
    }
  }, [notify]);

  const saveDemoMedia = useCallback((files: File[]) => {
    const additions = files.map((file) => ({
      id: crypto.randomUUID(),
      name: file.name,
      type: file.type || "Unknown media",
      size: file.size,
      addedAt: new Date().toISOString(),
    }));
    try {
      const next = [...additions, ...readStorage<DemoMediaAsset[]>(MEDIA_KEY, [])];
      window.localStorage.setItem(MEDIA_KEY, JSON.stringify(next));
      setMedia(next);
      notify(`${files.length} file${files.length === 1 ? "" : "s"} added as local demo metadata. No file was uploaded.`);
    } catch {
      notify("Could not save media metadata in browser storage.", "error");
    }
  }, [notify]);

  const removeDemoMedia = useCallback((id: string) => {
    try {
      const next = readStorage<DemoMediaAsset[]>(MEDIA_KEY, []).filter((item) => item.id !== id);
      window.localStorage.setItem(MEDIA_KEY, JSON.stringify(next));
      setMedia(next);
      notify("Local media metadata removed.");
    } catch {
      notify("Could not update browser storage.", "error");
    }
  }, [notify]);

  const value = useMemo<StudioUIContextValue>(() => ({
    projects,
    media,
    openNewProject: () => setDialog("project"),
    openImportMedia: () => setDialog("media"),
    saveDemoProject,
    saveDemoMedia,
    removeDemoMedia,
    notify,
  }), [media, notify, projects, removeDemoMedia, saveDemoMedia, saveDemoProject]);

  return (
    <StudioUIContext.Provider value={value}>
      <div className="studio-shell">
        <Sidebar isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />
        <div className="main-panel">
          <Topbar
            onOpenNewProject={() => setDialog("project")}
            onToggleNav={() => setSidebarOpen((open) => !open)}
          />
          <main className="page-content">{children}</main>
        </div>
      </div>
      {dialog === "project" ? (
        <NewProjectDialog onClose={() => setDialog(null)} onSave={saveDemoProject} />
      ) : null}
      {dialog === "media" ? (
        <ImportMediaDialog onClose={() => setDialog(null)} onSave={saveDemoMedia} />
      ) : null}
      {notice ? (
        <div aria-live="polite" className={`toast toast-${notice.tone}`} role="status">
          <span className="toast-indicator" />
          {notice.message}
          <button aria-label="Dismiss notification" onClick={() => setNotice(null)} type="button">
            <X size={15} />
          </button>
        </div>
      ) : null}
    </StudioUIContext.Provider>
  );
}
